"""Main philosophy debate graph with Tavily and Wikipedia retrieval."""

import sys
import json
import re
from pathlib import Path

# Add src to path so philo_agent can be imported
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

from philo_agent.schemas.philosopher import (
    PhilosopherSet,
    DebateTurn,
    PhilosophyAgentState,
    InputState,
)
from philo_agent.graphs.create_philosophers import create_philosophers
from philo_agent.retrieval.retrieve_tavily import retrieval_map
from philo_agent.retrieval import enrich_tavily_results

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
- Respond directly to the previous philosopher's question or argument
- Defend your philosophical position
- Challenge the opponent's reasoning
- End with a probing philosophical question for them

Opponent's last argument:
{last_argument}

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
    
    # Each philosopher responds in sequence to the previous one's question
    for i, p in enumerate(philosophers):
        # Determine what the previous philosopher said
        if history:
            last_turn = history[-1]
            last_argument = (
                last_turn.question
                if hasattr(last_turn, "question")
                else last_turn.get("question", "")
            )
        else:
            last_argument = f"Begin the debate on {state.get('topic', 'the topic')}"
        
        # Extract and format sources
        sources_list = p.get("sources", [])
        if isinstance(sources_list, dict) and "results" in sources_list:
            sources_list = sources_list["results"]
        
        # Format sources for prompt
        if isinstance(sources_list, list):
            sources_text = "\n".join(
                [f"- {s.get('title', s.get('query', 'Source'))}" for s in sources_list[:3]]
            )
        else:
            sources_text = str(sources_list)[:500]
        
        # Generate response without tool-calling
        resp = llm.invoke(
            DEBATE_PROMPT.format(
                name=p["philosopher"].name,
                school=p["philosopher"].school,
                last_argument=last_argument,
                sources=sources_text,
            )
        )
        text = getattr(resp, "content", None) or str(resp)
        
        # Parse JSON response
        try:
            parsed = json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                parsed = {
                    "speaker": p["philosopher"].name,
                    "argument": text[:500],
                    "question": "What do you think?",
                }
            else:
                parsed = json.loads(match.group(0))
        
        turn = DebateTurn.parse_obj(parsed)
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
        speaker = (
            turn.speaker if hasattr(turn, "speaker") else turn.get("speaker", "Unknown")
        )
        argument = (
            turn.argument
            if hasattr(turn, "argument")
            else turn.get("argument", "")
        )
        question = (
            turn.question if hasattr(turn, "question") else turn.get("question", "")
        )
        
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


# Build the main debate graph
graph = StateGraph(PhilosophyAgentState)

graph.add_node("philosophers", create_philosophers)
graph.add_node("retrieve", retrieval_map)
graph.add_node("enrich", enrich_and_retrieve)
graph.add_node("debate", debate_turn)
graph.add_node("format", format_dialogue)

# Set edges
graph.set_entry_point("philosophers")
graph.add_edge("philosophers", "retrieve")
graph.add_edge("retrieve", "enrich")
graph.add_edge("enrich", "debate")

# Conditional loop for 5 turns
graph.add_conditional_edges("debate", should_continue_debate)
graph.add_edge("format", END)

# Compile the graph
app = graph.compile()
