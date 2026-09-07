"""FastAPI backend for the philosophical debate simulator.

Exposes:
- POST /debate            legacy: runs the full debate, returns `{"dialogue": ...}`
- POST /debate/stream     Server-Sent Events stream of debate progress

The streaming endpoint uses LangGraph's async streaming (`stream_mode="updates"`)
so clients receive live events as each stage of the pipeline completes.
"""

import asyncio
import json
import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from philo_agent.graphs.main_graph import app as debate_graph
from philo_agent.graphs.main_graph import run_debate

app = FastAPI(title="Philosophical Debate API")

# Comma-separated list of allowed browser origins (deployed SPA URLs).
# Override via the CORS_ORIGINS environment variable.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"
cors_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DebateRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="The philosophical topic to debate")


class DebateResponse(BaseModel):
    dialogue: str


def sse(event: str, data: Any) -> str:
    """Serialize a single Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/debate", response_model=DebateResponse)
async def debate(req: DebateRequest):
    """Run the full debate and return the formatted dialogue."""
    output = await asyncio.to_thread(run_debate, req.topic)
    return {"dialogue": output}


@app.post("/debate/stream")
async def debate_stream(req: DebateRequest):
    """Stream the debate as Server-Sent Events."""
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }

    async def event_generator():
        seen_history = 0
        try:
            async for update in debate_graph.astream(
                {"topic": req.topic}, stream_mode="updates"
            ):
                for node, state in update.items():
                    if node == "philosophers":
                        philosopher_set = state.get("philosopher_set")
                        if philosopher_set is not None:
                            yield sse(
                                "philosophers",
                                {
                                    "philosophers": [
                                        p.model_dump() for p in philosopher_set.philosophers
                                    ]
                                },
                            )
                    elif node == "retrieve":
                        yield sse("status", {"message": "Gathering sources via Tavily..."})
                    elif node == "enrich":
                        yield sse(
                            "status",
                            {"message": "Enriching sources with Wikipedia summaries..."},
                        )
                    elif node == "debate":
                        history = state.get("history", [])
                        new_turns = history[seen_history:]
                        for turn in new_turns:
                            speaker = getattr(turn, "speaker", None) or turn.get("speaker", "")
                            argument = getattr(turn, "argument", None) or turn.get("argument", "")
                            question = getattr(turn, "question", None) or turn.get("question", "")
                            yield sse(
                                "turn",
                                {
                                    "round": state.get("turn_count", 0),
                                    "speaker": speaker,
                                    "argument": argument,
                                    "question": question,
                                },
                            )
                        seen_history = len(history)
                    elif node == "format":
                        yield sse("done", {"dialogue": state.get("final_dialogue", "")})
        except Exception as exc:  # surface failures to the client
            yield sse("error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)