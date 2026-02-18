import sys
from pathlib import Path


from fastapi import FastAPI
from pydantic import BaseModel
from main import run_debate

app = FastAPI(title="Philosophical Debate API")


class DebateRequest(BaseModel):
    topic: str


class DebateResponse(BaseModel):
    dialogue: str


@app.post("/debate", response_model=DebateResponse)
async def debate(req: DebateRequest):
    """
    Run philosophical debate simulation.
    """
    output = run_debate(req.topic)

    return {
        "dialogue": output
    }
