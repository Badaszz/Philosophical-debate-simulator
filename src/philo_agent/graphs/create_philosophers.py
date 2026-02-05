"""Philosopher creation graph node."""

import json
import re
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

from philo_agent.schemas.philosopher import PhilosopherSet, PhilosophyAgentState, InputState

# Load environment
load_dotenv()

# Initialize LLM
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.1,
    max_retries=2,
)

# Create philosopher prompt
PHILOSOPHER_PROMPT = ChatPromptTemplate.from_template("""
You are a philosophy professor.

Given a philosophical concept, do the following:
1. Identify its strongest opposing philosophical position.
2. Create two philosopher profiles:
   - One defending the original concept
   - One defending the opposing concept

Use historical realism when possible.

Concept: {topic}

IMPORTANT: Respond ONLY with a valid JSON object. Do NOT use any tools. The JSON must have this exact structure:
{{
  "topic": "...",
  "opposing_topic": "...",
  "philosophers": [
    {{"name": "...", "school": "...", "stance": "...", "core_claims": [...], "argumentative_style": "...", "primary_goal": "..."}},
    {{"name": "...", "school": "...", "stance": "...", "core_claims": [...], "argumentative_style": "...", "primary_goal": "..."}}
  ]
}}
""")


def create_philosophers(state: InputState) -> PhilosophyAgentState:
    """Create two opposing philosophers for a debate topic.
    
    Args:
        state: InputState containing topic
        
    Returns:
        Updated state with philosopher_set and turn_count initialized
    """
    topic = state.get("topic", "Free Will")
    
    # Use plain invoke to avoid tool-calling
    resp = llm.invoke(PHILOSOPHER_PROMPT.format(topic=topic))
    text = getattr(resp, 'content', None) or str(resp)
    
    # Parse JSON from response
    try:
        parsed = json.loads(text)
    except Exception:
        # Try to extract JSON object from text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            raise ValueError(f"Could not extract JSON from response: {text[:200]}")
        parsed = json.loads(match.group(0))
    
    # Validate and create PhilosopherSet
    philosopher_set = PhilosopherSet.parse_obj(parsed)
    return {**state, "philosopher_set": philosopher_set, "turn_count": 0}
