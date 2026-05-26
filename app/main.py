"""A2A_min_v1 Gateway — minimal startup entry."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    print("Gateway Started — A2A_min_v1")
    yield


app = FastAPI(title="A2A_min_v1 Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
