"""Main philosophy debate graph with Tavily and Wikipedia retrieval.

This module is the single source of truth for the debate pipeline:

    [philosophers] -> [retrieve] -> [enrich] -> [debate] --(loop x5)--> [format] -> END
"""

import json
import re

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langgraph.graph import END, StateGraph

from philo_agent.graphs.create_philosophers import create_philosophers
from philo_agent.retrieval import enrich_tavily_results
from philo_agent.retrieval.retrieve_tavily import retrieval_map
from philo_agent.schemas.philosopher import (
    DebateTurn,
    InputState,
    PhilosophyAgentState,
)

# Load environment
load_dotenv()

# Initialize LLM
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.1,
    max_retries=2,
)

# Debate prompt template
DEBATE_PROMPT = ChatPromptTemplate.from_template("""
You are {name}, a philosopher from the {school} tradition.

Your task:
- If the previous philosopher asked a question, answer it explicitly and directly in the first part of your argument before introducing new points
- Address the previous philosopher's argument and explain whether you agree or disagree
- Defend your philosophical position
- Challenge the opponent's reasoning
- End with a probing philosophical question for them

Previous philosopher's argument:
{previous_argument}

Previous philosopher's question (answer this directly; do not ignore it):
{previous_question}

Your sources:
{sources}

IMPORTANT: Respond ONLY with a valid JSON object. Do NOT use any tools. The JSON must have this exact structure:
{{
  "speaker": "{name}",
  "argument": "...",
  "question": "..."
}}
""")


def enrich_and_retrieve(state: PhilosophyAgentState) -> PhilosophyAgentState:
    """Retrieve Tavily results and enrich with Wikipedia summaries.

    Args:
        state: PhilosophyAgentState with enriched_philosophers

    Returns:
        Updated state with Wikipedia-enriched sources
    """
    enriched_philosophers = state.get("enriched_philosophers", [])

    # Enrich each philosopher's sources with Wikipedia summaries
    for phil_data in enriched_philosophers:
        sources_list = phil_data.get("sources", {})

        # Extract Tavily results if in dict format
        if isinstance(sources_list, dict) and "results" in sources_list:
            sources_list = sources_list["results"]

        # Enrich with Wikipedia
        if isinstance(sources_list, list):
            phil_data["sources"] = enrich_tavily_results(sources_list)
        else:
            phil_data["sources"] = []

    return {**state, "enriched_philosophers": enriched_philosophers, "history": []}


def debate_turn(state: PhilosophyAgentState) -> PhilosophyAgentState:
    """Generate one round of debate where each philosopher responds.

    Args:
        state: PhilosophyAgentState with enriched_philosophers and history

    Returns:
        Updated state with debate turns added to history
    """
    history = state.get("history", [])
    philosophers = state["enriched_philosophers"]
    turn_count = state.get("turn_count", 0)

    turns = []

    for p in philosophers:
        preceding_turns = history + turns
        if preceding_turns:
            last_turn = preceding_turns[-1]
            previous_argument = (
                last_turn.argument
                if hasattr(last_turn, "argument")
                else last_turn.get("argument", "")
            )
            previous_question = (
                last_turn.question
                if hasattr(last_turn, "question")
                else last_turn.get("question", "")
            )
        else:
            previous_argument = f"Begin the debate on {state.get('topic', 'the topic')}"
            previous_question = "No question has been asked yet; open the debate by stating your position."

        sources_list = p.get("sources", [])
        if isinstance(sources_list, dict) and "results" in sources_list:
            sources_list = sources_list["results"]

        if isinstance(sources_list, list):
            sources_text = "\n".join(
                [
                    f"- {s.get('title', s.get('query', 'Source'))}: {s.get('content', s.get('snippet', ''))}".strip(": ")
                    for s in sources_list[:3]
                ]
            )
        else:
            sources_text = str(sources_list)[:500]

        resp = llm.invoke(
            DEBATE_PROMPT.format(
                name=p["philosopher"].name,
                school=p["philosopher"].school,
                previous_argument=previous_argument,
                previous_question=previous_question,
                sources=sources_text,
            )
        )
        text = getattr(resp, "content", None) or str(resp)

        try:
            parsed = json.loads(text, strict=False)
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                parsed = {
                    "speaker": p["philosopher"].name,
                    "argument": text[:500],
                    "question": "What do you think?",
                }
            else:
                parsed = json.loads(match.group(0), strict=False)

        try:
            turn = DebateTurn.model_validate(parsed)
        except Exception:
            turn = DebateTurn(
                speaker=p["philosopher"].name,
                argument=parsed.get("argument", text[:500]),
                question=parsed.get("question", "What do you think?"),
            )
        turns.append(turn)

    return {**state, "history": history + turns, "turn_count": turn_count + 1}


def format_dialogue(state: PhilosophyAgentState) -> PhilosophyAgentState:
    """Format the debate history into a readable dialogue.

    Args:
        state: PhilosophyAgentState with history

    Returns:
        Updated state with final_dialogue key
    """
    dialogue = []
    for turn in state["history"]:
        # Handle both Pydantic objects and dicts
        speaker = turn.speaker if hasattr(turn, "speaker") else turn.get("speaker", "Unknown")
        argument = turn.argument if hasattr(turn, "argument") else turn.get("argument", "")
        question = turn.question if hasattr(turn, "question") else turn.get("question", "")

        dialogue.append(f"{speaker}:\n{argument}\n\nQuestion:\n{question}\n")

    return {**state, "final_dialogue": "\n---\n".join(dialogue)}


def should_continue_debate(state: PhilosophyAgentState) -> str:
    """Determine if debate should continue for another turn.

    Args:
        state: PhilosophyAgentState with turn_count

    Returns:
        "debate" to continue or "format" to finish
    """
    turn_count = state.get("turn_count", 0)
    if turn_count < 5:
        return "debate"
    return "format"


def build_graph():
    """Build and compile the debate graph.

    Only `InputState` (a single `topic`) is exposed to external callers;
    the internal keys live on the full `PhilosophyAgentState`.
    """
    graph = StateGraph(PhilosophyAgentState, input=InputState)

    graph.add_node("philosophers", create_philosophers)
    graph.add_node("retrieve", retrieval_map)
    graph.add_node("enrich", enrich_and_retrieve)
    graph.add_node("debate", debate_turn)
    graph.add_node("format", format_dialogue)

    graph.set_entry_point("philosophers")
    graph.add_edge("philosophers", "retrieve")
    graph.add_edge("retrieve", "enrich")
    graph.add_edge("enrich", "debate")

    # Conditional loop for 5 turns
    graph.add_conditional_edges("debate", should_continue_debate)
    graph.add_edge("format", END)

    return graph.compile()


# Compiled graph, reused across requests and by `langgraph dev`.
app = build_graph()


def run_debate(topic: str) -> str:
    """Run a full debate synchronously and return the formatted dialogue."""
    result = app.invoke({"topic": topic})
    return result["final_dialogue"]