"""Tavily search retrieval for philosopher knowledge."""

import os
from tavily import TavilyClient


def get_tavily_client():
    """Get or create a Tavily client."""
    api_key = os.getenv('TAVILY_API_KEY')
    if not api_key:
        raise RuntimeError('TAVILY_API_KEY not set in environment')
    return TavilyClient(api_key=api_key)


def retrieve_philosophy_knowledge(philosopher, max_results: int = 5):
    """Retrieve philosophical knowledge for a philosopher using Tavily.
    
    Args:
        philosopher: A PhilosopherProfile object
        max_results: Maximum number of search results to return
        
    Returns:
        dict with 'philosopher' and 'sources' keys
    """
    tavily_client = get_tavily_client()
    query = f"{philosopher.school} philosophy arguments criticisms"
    
    try:
        docs = tavily_client.search(query, max_results=max_results)
    except Exception as e:
        docs = []
    
    return {
        "philosopher": philosopher,
        "sources": docs
    }


def retrieval_map(state):
    """Map retrieval over all philosophers in the debate.
    
    Args:
        state: PhilosophyAgentState dict
        
    Returns:
        Updated state with enriched_philosophers and empty history
    """
    philosophers = state["philosopher_set"].philosophers
    enriched = [
        retrieve_philosophy_knowledge(p) for p in philosophers
    ]
    return {**state, "enriched_philosophers": enriched, "history": []}
