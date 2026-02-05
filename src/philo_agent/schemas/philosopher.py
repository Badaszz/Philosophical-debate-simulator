"""Philosopher and debate schemas."""

from pydantic import BaseModel
from typing import List, TypedDict


class PhilosopherProfile(BaseModel):
    """A philosopher profile with their stance and arguments."""
    name: str
    school: str
    stance: str
    core_claims: List[str]
    argumentative_style: str
    primary_goal: str


class PhilosopherSet(BaseModel):
    """A set of philosophers debating a topic."""
    topic: str
    opposing_topic: str
    philosophers: List[PhilosopherProfile]


class DebateTurn(BaseModel):
    """A single turn in the debate."""
    speaker: str
    argument: str
    question: str


class PhilosophyAgentState(TypedDict, total=False):
    """The state schema for the philosophy debate agent."""
    topic: str
    philosopher_set: PhilosopherSet
    enriched_philosophers: list
    history: list
    final_dialogue: str
    turn_count: int
