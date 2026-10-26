# Evaluation

`evaluate_debates.py` runs the debate agent over a set of topics and grades every
turn with a second LLM (the "judge"). It is useful for measuring whether changes
to the agent's prompts, retrieval, or models actually improve output quality.

## What gets scored

Each turn is scored from 0-10 on:

| Dimension | Meaning |
|---|---|
| Validity | Do the premises support the conclusion? Any fallacies? |
| Hallucination control | Factual accuracy of attributions, quotes, and doctrines. **10 = no hallucination.** |
| Adherence to topic | Stays on the debate topic. |
| Adherence to previous argument | Directly answers/challenges the opponent's previous turn instead of monologuing. |
| Coherence | Clear, well-structured, non-contradictory. |
| Use of philosophical knowledge | Accurate, relevant philosophical content. |

The judge also returns debate-level `overall_quality` and `philosophical_depth`,
plus strengths, weaknesses, recommendations, and a summary.

## Running it

Use the backend virtualenv (it already has `langchain-groq`, `langgraph`, etc.):

```powershell
# Five-topic smoke suite
.\backend\.venv\Scripts\python.exe eval\evaluate_debates.py --quick

# Custom topics, JSON + README-ready markdown
.\backend\.venv\Scripts\python.exe eval\evaluate_debates.py `
    --topics eval\topics.example.json `
    --output eval\results.json `
    --markdown eval\results.md
```

On macOS/Linux use `backend/.venv/bin/python` instead.

Useful flags:

| Flag | Purpose |
|---|---|
| `--quick` | Built-in five-topic suite. |
| `--topics FILE` | JSON list of topics. |
| `--limit N` | Only run the first N topics. |
| `--output FILE` | Raw JSON results (default `eval/results.json`). |
| `--markdown FILE` | Write a README-ready markdown report. |
| `--judge-model NAME` | Judge model (default `openai/gpt-oss-20b`, override with `EVAL_JUDGE_MODEL`). |
| `--judge-temperature X` | Judge temperature (default `0.0`). |
| `--agent-retries N` | Retry a debate if the agent emits malformed JSON (default `3`). |
| `--from-results FILE` | Re-score saved dialogues without re-running the agent. |
| `--update-readme README` | Replace the block between `EVAL_RESULTS_START`/`EVAL_RESULTS_END` in the given README with the generated report. |

## Iterating on the agent

1. Run the evaluation and note the weakest dimension(s).
2. Look at the raw JSON (`results.json`) for the specific turns and judge comments.
3. Change the agent (prompts in `backend/philo_agent/graphs/`, retrieval, temperature).
4. Re-run the evaluation, or use `--from-results` to re-score the same transcripts
   after changing only the judge prompt.
5. When the scores are acceptable, paste the generated markdown (`eval/results.md`)
   into the main `README.md`, or run with `--update-readme README.md` to replace
   the marked results block automatically.

The agent's own LLM occasionally returns malformed JSON. The evaluator retries
those debates (`--agent-retries`) and skips topics that still fail, so a single bad
sample does not abort the whole suite.
