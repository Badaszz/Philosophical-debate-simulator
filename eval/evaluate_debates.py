#!/usr/bin/env python3
"""LLM-judged evaluation of the philosophical debate agent.

The script can do two things:

1. Run the debate agent on a set of topics and score every turn with an LLM
   judge (default).
2. Re-score previously saved dialogues without re-running the agent
   (``--from-results``), which is useful while iterating on prompt/judge
   changes without paying for new debates.

The judge scores each turn on validity, hallucination (inverted: 10 = none),
topic adherence, adherence to the previous argument, coherence, and use of
sources. It also produces debate-level strengths/weaknesses/recommendations.

Examples
--------
Run the default quick suite with the backend virtualenv::

    .\\backend\\.venv\\Scripts\\python.exe eval\\evaluate_debates.py --quick

Run custom topics and write a README-ready markdown report::

    .\\backend\\.venv\\Scripts\\python.exe eval\\evaluate_debates.py \\
        --topics eval\\topics.json --output eval\\results.json \\
        --markdown eval\\results.md

Re-score saved dialogues after changing the judge prompt::

    .\\backend\\.venv\\Scripts\\python.exe eval\\evaluate_debates.py \\
        --from-results eval\\results.json --output eval\\rescore.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402
from langchain_groq import ChatGroq  # noqa: E402
from pydantic import BaseModel, Field, ValidationError  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

DEFAULT_QUICK_TOPICS = [
    "Is free will compatible with determinism?",
    "Does morality require religion?",
    "Is consciousness physical or non-physical?",
    "Should we prioritize individual liberty or collective welfare?",
    "Is there objective beauty?",
]

SCORE_KEYS = [
    "validity",
    "hallucination",
    "adherence_to_topic",
    "adherence_to_previous",
    "coherence",
    "uses_sources_well",
]

SCORE_LABELS = {
    "validity": "Validity",
    "hallucination": "Hallucination control (10 = none)",
    "adherence_to_topic": "Adherence to topic",
    "adherence_to_previous": "Adherence to previous argument",
    "coherence": "Coherence",
    "uses_sources_well": "Use of philosophical knowledge",
}


class TurnEvaluation(BaseModel):
    """Scores for a single debate turn (all 0-10)."""

    validity: float = Field(ge=0, le=10, description="Logical validity of the argument")
    hallucination: float = Field(
        ge=0,
        le=10,
        description="Factual accuracy; 10 means no hallucination or misattribution",
    )
    adherence_to_topic: float = Field(ge=0, le=10, description="Stays on the debate topic")
    adherence_to_previous: float = Field(
        ge=0,
        le=10,
        description="Directly engages the opponent's previous argument/question",
    )
    coherence: float = Field(ge=0, le=10, description="Clarity and structure")
    uses_sources_well: float = Field(
        ge=0, le=10, description="Appropriate use of philosophical knowledge"
    )
    comments: str = Field(default="", description="Short justification of the scores")


class DebateEvaluation(BaseModel):
    """Debate-level evaluation returned by the judge."""

    overall_quality: float = Field(ge=0, le=10)
    philosophical_depth: float = Field(ge=0, le=10)
    turn_evaluations: list[TurnEvaluation]
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    summary: str = Field(default="")


JUDGE_PROMPT = ChatPromptTemplate.from_template(
    """You are a rigorous philosophy professor grading a staged debate between two
philosophers. Judge the text itself; do not assume good faith.

Topic: {topic}

There are exactly {num_turns} turns in this debate:
{debate}

Grade EVERY turn independently on these 0-10 scales:
- validity: do the premises support the conclusion? Are there logical fallacies?
- hallucination: factual accuracy of attributions, quotes, dates, and doctrines.
  10 = fully accurate; 0 = major fabricated claims or false attributions.
- adherence_to_topic: stays relevant to the debate topic.
- adherence_to_previous: actually answers or challenges the immediately previous
  turn instead of monologuing or repeating itself.
- coherence: clear, well-structured, non-contradictory.
- uses_sources_well: demonstrates accurate philosophical knowledge.

Then give debate-level overall_quality and philosophical_depth (0-10), plus
strengths, weaknesses, recommendations (short bullet lists) and a summary.

CRITICAL: ``turn_evaluations`` must contain exactly {num_turns} entries, one per
numbered turn, in order. Do not merge, split, duplicate, or skip turns. Each
entry scores only that turn's argument, not its question separately.

Pay special attention to:
- Hallucinations such as invented quotes, anachronisms, or views a philosopher
  never held.
- Turns that ignore the opponent's question and just restate their own position.
- Circular reasoning, equivocation, and unsupported empirical claims.

Return ONLY valid JSON with this shape:
{{
  "overall_quality": 0-10,
  "philosophical_depth": 0-10,
  "turn_evaluations": [
    {{
      "validity": 0-10,
      "hallucination": 0-10,
      "adherence_to_topic": 0-10,
      "adherence_to_previous": 0-10,
      "coherence": 0-10,
      "uses_sources_well": 0-10,
      "comments": "..."
    }}
  ],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "recommendations": ["..."],
  "summary": "..."
}}"""
)


def log(message: str) -> None:
    """Print progress immediately, even when stdout is piped."""
    print(message, flush=True)


def configure_console() -> None:
    """Avoid UnicodeEncodeError on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def make_judge(model: str, temperature: float = 0.0) -> ChatGroq:
    """Create the Groq chat model used as the judge."""
    options: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_retries": 2,
        "max_tokens": 8192,
    }
    if "gpt-oss" in model.lower() or "reasoning" in model.lower():
        options["reasoning_effort"] = "low"
    return ChatGroq(**options)


def extract_json(
    text: str, required_keys: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Extract the first valid JSON object from a model response.

    Judges occasionally prepend reasoning, wrap JSON in markdown fences, or use
    smart quotes. ``json.loads`` alone is too brittle, so scan for the first
    decodable object. ``required_keys`` prevents accidentally returning a
    nested object from a truncated response.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    candidates = [text, text.replace("\u201c", '"').replace("\u201d", '"')]

    def acceptable(value: Any) -> bool:
        return isinstance(value, dict) and all(key in value for key in required_keys)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                decoded, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if acceptable(decoded):
                return decoded

    for candidate in candidates:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                decoded = ast.literal_eval(candidate[start : end + 1])
            except (ValueError, SyntaxError):
                continue
            if acceptable(decoded):
                return decoded

    raise ValueError(f"No usable JSON object found in response: {text[:500]!r}")


def parse_debate_turns(dialogue: str) -> list[dict[str, str]]:
    """Split a formatted dialogue into (speaker, argument, question) turns."""
    turns: list[dict[str, str]] = []
    for section in dialogue.split("\n---\n"):
        section = section.strip()
        if not section:
            continue
        lines = section.split("\n")
        speaker = lines[0].rstrip(":").strip()
        content = "\n".join(lines[1:])
        if "Question:" in content:
            argument, question = content.split("Question:", 1)
        else:
            argument, question = content, ""
        turns.append(
            {
                "speaker": speaker,
                "argument": argument.strip(),
                "question": question.strip(),
            }
        )
    return turns


def format_numbered_turns(turns: list[dict[str, str]]) -> str:
    """Render turns with explicit numbering so the judge scores one per turn."""
    blocks = []
    for index, turn in enumerate(turns, start=1):
        blocks.append(
            f"Turn {index} — {turn['speaker']}:\n"
            f"Argument: {turn['argument']}\n"
            f"Question: {turn['question']}"
        )
    return "\n\n".join(blocks)


def evaluate_dialogue(
    topic: str,
    dialogue: str,
    judge: ChatGroq,
    retries: int = 3,
) -> DebateEvaluation | None:
    """Score a single debate with the LLM judge."""
    turns = parse_debate_turns(dialogue)
    expected = len(turns)
    numbered = format_numbered_turns(turns)

    last_error: Exception | None = None
    last_text = ""
    for attempt in range(1, retries + 1):
        try:
            response = judge.invoke(
                JUDGE_PROMPT.format(
                    topic=topic, debate=numbered, num_turns=expected
                )
            )
            text = getattr(response, "content", None) or str(response)
            last_text = text
            data = extract_json(
                text, required_keys=("overall_quality", "turn_evaluations")
            )
            evaluation = DebateEvaluation.model_validate(data)
            if len(evaluation.turn_evaluations) != expected:
                raise ValueError(
                    "judge returned "
                    f"{len(evaluation.turn_evaluations)} turn scores, "
                    f"expected {expected}"
                )
            return evaluation
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            log(f"    judge attempt {attempt}/{retries} failed: {exc}")
            time.sleep(1.5 * attempt)
    log(f"    judge failed permanently: {last_error}")
    if last_text:
        log(f"    raw judge output (first 800 chars): {last_text[:800]!r}")
    return None


def run_agent(topic: str) -> str:
    """Import and run the debate graph lazily so offline mode works without it."""
    from philo_agent.graphs.main_graph import run_debate

    return run_debate(topic)


def evaluate_topic(
    topic: str,
    judge: ChatGroq,
    dialogue: str | None = None,
    agent_retries: int = 3,
) -> dict[str, Any] | None:
    """Run (or reuse) a debate and score it."""
    if dialogue is None:
        for attempt in range(1, agent_retries + 1):
            log(f"  running debate agent (attempt {attempt}/{agent_retries})...")
            started = time.perf_counter()
            try:
                dialogue = run_agent(topic)
                log(f"  debate finished in {time.perf_counter() - started:.1f}s")
                break
            except Exception as exc:  # noqa: BLE001 - keep the suite running
                log(f"  agent attempt {attempt} failed: {exc}")
                dialogue = None
                time.sleep(2 * attempt)
        if dialogue is None:
            log("  agent failed after all retries; skipping topic")
            return None

    turns = parse_debate_turns(dialogue)
    log(f"  generated {len(turns)} turns; judging...")
    evaluation = evaluate_dialogue(topic, dialogue, judge)
    if evaluation is None:
        return None

    return {
        "topic": topic,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_turns": len(turns),
        "dialogue": dialogue,
        "turns": turns,
        "evaluation": evaluation.model_dump(),
    }


def average(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 2) if values else None


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the results into a compact summary dictionary."""
    turn_scores: dict[str, list[float]] = {key: [] for key in SCORE_KEYS}
    quality: list[float] = []
    depth: list[float] = []

    for result in results:
        evaluation = result["evaluation"]
        quality.append(float(evaluation.get("overall_quality", 0)))
        depth.append(float(evaluation.get("philosophical_depth", 0)))
        for turn in evaluation.get("turn_evaluations", []):
            for key in SCORE_KEYS:
                turn_scores[key].append(float(turn.get(key, 0)))

    averaged_scores = {key: average(values) for key, values in turn_scores.items()}
    scored_dimensions = {
        key: value for key, value in averaged_scores.items() if value is not None
    }
    weakest = (
        min(scored_dimensions, key=scored_dimensions.get) if scored_dimensions else None
    )

    return {
        "num_debates": len(results),
        "num_turns": sum(result["num_turns"] for result in results),
        "overall_quality": average(quality),
        "philosophical_depth": average(depth),
        "turn_scores": averaged_scores,
        "weakest_dimension": weakest,
    }


def print_report(results: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """Print a human-readable report to stdout."""
    log("\n" + "=" * 64)
    log("EVALUATION SUMMARY")
    log("=" * 64)
    for result in results:
        evaluation = result["evaluation"]
        log(
            f"- {result['topic']}: quality={evaluation.get('overall_quality')}/10, "
            f"depth={evaluation.get('philosophical_depth')}/10, "
            f"turns={result['num_turns']}"
        )
        if evaluation.get("summary"):
            log(f"    {evaluation['summary']}")

    log("-" * 64)
    log(f"Debates: {summary['num_debates']} | Turns scored: {summary['num_turns']}")
    log(f"Average quality: {summary['overall_quality']}/10")
    log(f"Average depth:   {summary['philosophical_depth']}/10")
    log("Average turn scores:")
    for key, value in summary["turn_scores"].items():
        log(f"  {SCORE_LABELS.get(key, key):<34} {value}/10")
    if summary.get("weakest_dimension"):
        weakest = summary["weakest_dimension"]
        log(f"Weakest dimension: {SCORE_LABELS.get(weakest, weakest)}")
    log("=" * 64 + "\n")


def render_markdown(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    judge_model: str | None = None,
) -> str:
    """Render a README-ready markdown section."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    judge_model = judge_model or os.getenv("EVAL_JUDGE_MODEL", "openai/gpt-oss-20b")
    lines = [
        "## Evaluation Results",
        "",
        f"_Generated {generated} with an LLM judge (`{judge_model}`)._",
        "",
        "### Aggregate scores",
        "",
        "| Metric | Score |",
        "|---|---|",
        f"| Debates evaluated | {summary['num_debates']} |",
        f"| Turns scored | {summary['num_turns']} |",
        f"| Overall quality | {summary['overall_quality']}/10 |",
        f"| Philosophical depth | {summary['philosophical_depth']}/10 |",
    ]
    for key, value in summary["turn_scores"].items():
        lines.append(f"| {SCORE_LABELS.get(key, key)} | {value}/10 |")
    if summary.get("weakest_dimension"):
        weakest = summary["weakest_dimension"]
        lines.append(f"| Weakest dimension | {SCORE_LABELS.get(weakest, weakest)} |")

    lines += [
        "",
        "### Per-topic",
        "",
        "| Topic | Quality | Depth | Turns |",
        "|---|---|---|---|",
    ]
    for result in results:
        evaluation = result["evaluation"]
        lines.append(
            f"| {result['topic']} | {evaluation.get('overall_quality')}/10 "
            f"| {evaluation.get('philosophical_depth')}/10 | {result['num_turns']} |"
        )

    lines += ["", "### Notable strengths and weaknesses", ""]
    for result in results:
        evaluation = result["evaluation"]
        lines.append(f"**{result['topic']}**")
        strengths = evaluation.get("strengths") or []
        weaknesses = evaluation.get("weaknesses") or []
        if strengths:
            lines.append("- Strengths: " + "; ".join(strengths))
        if weaknesses:
            lines.append("- Weaknesses: " + "; ".join(weaknesses))
        if evaluation.get("summary"):
            lines.append(f"- Summary: {evaluation['summary']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


EVAL_START = "<!-- EVAL_RESULTS_START -->"
EVAL_END = "<!-- EVAL_RESULTS_END -->"


def update_readme(readme_path: Path, markdown: str) -> None:
    """Insert or replace the evaluation section between README markers."""
    content = readme_path.read_text(encoding="utf-8")
    section = f"{EVAL_START}\n{markdown.strip()}\n{EVAL_END}"
    pattern = re.compile(
        re.escape(EVAL_START) + r".*?" + re.escape(EVAL_END), re.DOTALL
    )
    if pattern.search(content):
        content = pattern.sub(lambda _match: section, content)
    else:
        content = content.rstrip() + "\n\n" + section + "\n"
    readme_path.write_text(content, encoding="utf-8")


def load_results(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if not isinstance(data, list):
        raise ValueError(f"Unsupported results format in {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topics", type=Path, help="JSON file containing a list of topics")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use the built-in five-topic smoke suite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "eval" / "results.json",
        help="Where to write raw JSON results",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="Optional path for a README-ready markdown report",
    )
    parser.add_argument(
        "--update-readme",
        type=Path,
        metavar="README",
        help=(
            "Replace the block between EVAL_RESULTS_START/EVAL_RESULTS_END "
            "markers in this README with the generated report"
        ),
    )
    parser.add_argument(
        "--from-results",
        type=Path,
        help="Re-score dialogues from a previous results file instead of running the agent",
    )
    parser.add_argument(
        "--judge-model",
        default=os.getenv("EVAL_JUDGE_MODEL", "openai/gpt-oss-20b"),
        help="Groq model used as the judge",
    )
    parser.add_argument(
        "--judge-temperature",
        type=float,
        default=0.0,
        help="Judge temperature (keep low for consistency)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only evaluate the first N topics",
    )
    parser.add_argument(
        "--agent-retries",
        type=int,
        default=3,
        help="How many times to retry a debate when the agent raises (default: 3)",
    )
    args = parser.parse_args()

    if not os.getenv("GROQ_API_KEY"):
        log("GROQ_API_KEY is not set; the judge and agent cannot run.")
        return 1

    configure_console()
    judge = make_judge(args.judge_model, args.judge_temperature)

    if args.from_results:
        log(f"Loading saved dialogues from {args.from_results}")
        saved = load_results(args.from_results)
        if args.limit:
            saved = saved[: args.limit]
        results: list[dict[str, Any]] = []
        for index, item in enumerate(saved, start=1):
            topic = item.get("topic", f"topic-{index}")
            dialogue = item.get("dialogue")
            if not dialogue:
                log(f"[{index}/{len(saved)}] {topic}: no dialogue, skipping")
                continue
            log(f"[{index}/{len(saved)}] Re-scoring: {topic}")
            evaluated = evaluate_topic(topic, judge, dialogue=dialogue)
            if evaluated:
                results.append(evaluated)
    else:
        if args.topics:
            with args.topics.open(encoding="utf-8") as handle:
                topics = json.load(handle)
        elif args.quick:
            topics = DEFAULT_QUICK_TOPICS
        else:
            topics = DEFAULT_QUICK_TOPICS[:1]
        if args.limit:
            topics = topics[: args.limit]

        results = []
        for index, topic in enumerate(topics, start=1):
            log(f"[{index}/{len(topics)}] {topic}")
            evaluated = evaluate_topic(
                topic, judge, agent_retries=args.agent_retries
            )
            if evaluated:
                results.append(evaluated)

    if not results:
        log("No debates were evaluated successfully.")
        return 1

    summary = summarise(results)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": args.judge_model,
        "summary": summary,
        "results": results,
    }
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    log(f"Raw results written to {args.output}")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        report = render_markdown(results, summary, args.judge_model)
        args.markdown.write_text(report, encoding="utf-8")
        log(f"Markdown report written to {args.markdown}")

    if args.update_readme:
        if not args.update_readme.exists():
            log(f"README not found: {args.update_readme}")
            return 1
        update_readme(
            args.update_readme,
            render_markdown(results, summary, args.judge_model),
        )
        log(f"Evaluation results written into {args.update_readme}")

    print_report(results, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
