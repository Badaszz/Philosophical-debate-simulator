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
from fastapi import Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
import tiktoken
from langsmith.run_helpers import tracing_context

from supabase_service import (
    AppUser,
    DAILY_REQUEST_LIMIT,
    add_allowed_user,
    claim_agent_call,
    get_admin_state,
    get_current_user,
    get_rate_limit_status,
    remove_allowed_user,
    require_admin,
    update_restriction,
)

from philo_agent.graphs.main_graph import app as debate_graph
from philo_agent.graphs.main_graph import run_debate

app = FastAPI(title="Philosophical Debate API")
TOPIC_TOKEN_LIMIT = 100
TOPIC_TOKENIZER = tiktoken.get_encoding("o200k_base")

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
    topic: str = Field(
        ..., min_length=1, max_length=10000,
        description="The philosophical topic to debate (maximum 100 tokens)",
    )

    @field_validator("topic")
    @classmethod
    def topic_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("topic must not be blank")
        token_count = len(TOPIC_TOKENIZER.encode(cleaned))
        if token_count > TOPIC_TOKEN_LIMIT:
            raise ValueError(
                f"topic must not exceed {TOPIC_TOKEN_LIMIT} tokens (received {token_count})"
            )
        return cleaned


class DebateResponse(BaseModel):
    dialogue: str


class RestrictionUpdate(BaseModel):
    restrict_sign_in: bool


class AllowedUserRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or "." not in cleaned.rsplit("@", 1)[-1]:
            raise ValueError("A valid email address is required.")
        return cleaned


def sse(event: str, data: Any) -> str:
    """Serialize a single Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/auth/me")
def auth_me(user: AppUser = Depends(get_current_user)):
    """Return the signed-in user's access and current rate-limit status."""
    status = get_rate_limit_status(user)
    return {
        "email": user.email,
        "is_admin": user.is_admin,
        "rate_limit_exempt": user.rate_limit_exempt,
        "remaining_seconds": int(status["remaining_seconds"] or 0),
        "available_at": status["available_at"],
        "total_requests": int(status["total_requests"]),
        "daily_request_count": int(status["daily_requests"]),
        "daily_limit": DAILY_REQUEST_LIMIT,
        "daily_remaining": int(status["daily_remaining"]),
        "daily_reset_at": status["daily_reset_at"],
    }


@app.get("/admin/state")
def admin_state(_: AppUser = Depends(require_admin)):
    return get_admin_state()


@app.put("/admin/settings")
def admin_update_settings(
    update: RestrictionUpdate, _: AppUser = Depends(require_admin)
):
    update_restriction(update.restrict_sign_in)
    return get_admin_state()


@app.post("/admin/allowed-users", status_code=204)
def admin_add_allowed_user(
    request: AllowedUserRequest, _: AppUser = Depends(require_admin)
):
    add_allowed_user(request.email)


@app.delete("/admin/allowed-users", status_code=204)
def admin_remove_allowed_user(
    request: AllowedUserRequest, _: AppUser = Depends(require_admin)
):
    remove_allowed_user(request.email)


@app.post("/debate", response_model=DebateResponse)
async def debate(req: DebateRequest, user: AppUser = Depends(get_current_user)):
    """Run the full debate and return the formatted dialogue."""
    await asyncio.to_thread(claim_agent_call, user)
    with tracing_context(enabled=False):
        output = await asyncio.to_thread(run_debate, req.topic)
    return {"dialogue": output}


@app.post("/debate/stream")
async def debate_stream(
    req: DebateRequest, user: AppUser = Depends(get_current_user)
):
    """Stream the debate as Server-Sent Events."""
    cooldown = await asyncio.to_thread(claim_agent_call, user)
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }

    async def event_generator():
        seen_history = 0
        try:
            yield sse(
                "cooldown",
                {
                    "exempt": user.rate_limit_exempt,
                    "remaining_seconds": int(cooldown["retry_after_seconds"] or 0),
                    "available_at": cooldown["available_at"],
                    "daily_request_count": int(cooldown["daily_requests"]),
                    "daily_limit": DAILY_REQUEST_LIMIT,
                    "daily_remaining": int(cooldown["daily_remaining"]),
                    "daily_reset_at": cooldown["daily_reset_at"],
                    "total_requests": int(cooldown["total_requests"]),
                },
            )
            with tracing_context(enabled=False):
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