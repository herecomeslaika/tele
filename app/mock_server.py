"""A2A_min_v1 Standalone Mock LLM Server — HTTP server for boundary testing."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from enum import Enum
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockScenario(str, Enum):
    NORMAL = "normal"
    DELAY = "delay"
    ERROR = "error"
    TIMEOUT = "timeout"
    MID_STREAM_ERROR = "mid_stream_error"
    BAD_JSON = "bad_json"
    DUPLICATE_TOKEN = "duplicate_token"
    OUT_OF_ORDER = "out_of_order"
    PARTIAL_DISCONNECT = "partial_disconnect"
    LONG_RESPONSE = "long_response"


app = FastAPI(title="Mock LLM Server")

# Global scenario (changeable at runtime via /scenario endpoint)
current_scenario = MockScenario.NORMAL
CHUNK_DELAY = 0.05


@app.post("/v1/chat/completions")
async def openai_completions(request: Request):
    """OpenAI-compatible /v1/chat/completions endpoint."""
    global current_scenario
    body = await request.json()
    stream = body.get("stream", False)
    model = body.get("model", "mock-model")
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 100)

    # Extract prompt
    prompt = ""
    for m in messages:
        if m.get("role") == "user":
            prompt += m.get("content", "")

    if not stream:
        return JSONResponse(content={
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"Mock response to: {prompt[:50]}"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": 10, "total_tokens": len(prompt) // 4 + 10},
        })

    # Streaming response
    async def generate():
        scenario = current_scenario

        if scenario == MockScenario.ERROR:
            yield f"data: {json.dumps({'error': {'message': 'Mock provider error', 'type': 'invalid_request_error'}})}\n\n"
            return

        if scenario == MockScenario.TIMEOUT:
            await asyncio.sleep(9999)
            return

        if scenario == MockScenario.BAD_JSON:
            yield "data: {malformed json}\n\n"
            yield "data: {broken\n\n"
            return

        tokens = ["Hello", " from", " mock", " server", "!"]
        chunk_id = f"chatcmpl-{int(time.time())}"

        for i, token in enumerate(tokens):
            if scenario == MockScenario.DELAY and i > 0:
                await asyncio.sleep(CHUNK_DELAY)

            if scenario == MockScenario.MID_STREAM_ERROR and i >= 2:
                yield f"data: {json.dumps({'error': {'message': 'Mid-stream error', 'type': 'api_error'}})}\n\n"
                return

            if scenario == MockScenario.DUPLICATE_TOKEN:
                for _ in range(2):
                    chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": token},
                            "finish_reason": None,
                        }],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                continue

            elif scenario == MockScenario.OUT_OF_ORDER:
                idx = len(tokens) - 1 - i
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": tokens[idx]},
                        "finish_reason": None,
                    }],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                continue

            elif scenario == MockScenario.PARTIAL_DISCONNECT:
                if i >= 2:
                    return

            elif scenario == MockScenario.LONG_RESPONSE:
                # Only emit long response on first iteration then return
                if i == 0:
                    for j in range(20):
                        chunk = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": f"word_{j} "},
                                "finish_reason": None,
                            }],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                        await asyncio.sleep(0.01)
                    done_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    yield f"data: {json.dumps(done_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

            # Normal scenario
            chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": token},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

        # Done
        done_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(done_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/scenario")
async def get_scenario():
    return {"scenario": current_scenario.value}


@app.post("/scenario")
async def set_scenario(request: Request):
    global current_scenario
    body = await request.json()
    scenario = body.get("scenario", "normal")
    try:
        current_scenario = MockScenario(scenario)
        return {"scenario": current_scenario.value, "status": "ok"}
    except ValueError:
        return JSONResponse(status_code=400, content={"error": f"Unknown scenario: {scenario}"})


@app.get("/health")
async def health():
    return {"status": "ok", "scenario": current_scenario.value}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock LLM Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)