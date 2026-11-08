from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Handover",
    description="Evidence-linked, permission-aware knowledge handover.",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}
