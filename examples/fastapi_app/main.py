"""
KeyForge demo — FastAPI app with API key auth and LLM token tracking.

Run:
    pip install 'keysigil[all]' uvicorn
    keysigil init
    keysigil create --name "demo-key" --rate-requests 10 --rate-window 1m --monthly-tokens 100000
    uvicorn examples.fastapi_app.main:app --reload

Then test:
    curl -H "X-API-Key: <your-key>" http://localhost:8000/hello
    curl -H "X-API-Key: <your-key>" http://localhost:8000/chat -X POST -d '{"prompt":"hi"}'
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from keysigil import KeyForge
from keysigil.middleware.fastapi import KeyForgeAuth

kf = KeyForge("sqlite:///keyforge.db")
auth = KeyForgeAuth(kf)
auth_llm = KeyForgeAuth(kf, require_permissions=["models.invoke"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await kf.setup()
    yield


app = FastAPI(title="KeyForge Demo", lifespan=lifespan)


@app.get("/hello", dependencies=[Depends(auth)])
async def hello(request: Request) -> dict:
    return {"message": f"Hello! Your key ID: {request.state.key_id}"}


class ChatRequest(BaseModel):
    prompt: str
    model: str = "gpt-4o-mini"


@app.post("/chat", dependencies=[Depends(auth_llm)])
async def chat(req: ChatRequest, request: Request) -> dict:
    # Simulate LLM call — track real usage here
    fake_input_tokens = len(req.prompt.split()) * 2
    fake_output_tokens = 50

    await kf.track_usage(
        key_id=request.state.key_id,
        input_tokens=fake_input_tokens,
        output_tokens=fake_output_tokens,
        model=req.model,
    )

    return {
        "response": f"Echo: {req.prompt}",
        "usage": {
            "input_tokens": fake_input_tokens,
            "output_tokens": fake_output_tokens,
            "model": req.model,
        },
    }


@app.get("/usage/me", dependencies=[Depends(auth)])
async def my_usage(request: Request) -> dict:
    stats = await kf.get_usage(request.state.key_id)
    return {
        "key_id": stats.key_id,
        "total_tokens": stats.total_tokens,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "by_model": stats.by_model,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
