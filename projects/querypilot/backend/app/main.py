import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.config import settings
from app.database import SessionLocal
from app.llm import describe_llm
from app.models import Connection, EvalRun
from app.routers import chat, connections, doctor, evals, glossary, memory, query, schema

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("querypilot")


def _warm_up() -> None:
    """Load the embedding model, chat model and pandas now, so the first question isn't the slow one."""
    import time

    from app.llm import get_llm
    from app.services import sandbox
    from app.services.embeddings import embed_texts

    started = time.perf_counter()
    for name, task in (
        ("embeddings", lambda: embed_texts(["warm up"], input_type="query")),
        ("chat model", lambda: get_llm().warm()),
        ("python sandbox", lambda: sandbox.run_python("result = 1", ["x"], [[1]])),
    ):
        try:
            task()
        except Exception as exc:  # noqa: BLE001 — warming must never stop the server
            logger.warning("Warm-up of %s failed: %s", name, exc)
    logger.info("Warm-up finished in %.1fs", time.perf_counter() - started)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Background work dies with the process; don't leave rows stuck in a running state.
    with SessionLocal() as db:
        db.execute(
            update(EvalRun).where(EvalRun.status == "running").values(status="error", error="Interrupted by a server restart.")
        )
        db.execute(
            update(Connection)
            .where(Connection.index_status.in_(("pending", "indexing")))
            .values(index_status="error", index_error="Indexing was interrupted by a server restart. Re-index to retry.")
        )
        db.commit()
    if settings.warmup_models_on_start:
        threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    yield


app = FastAPI(title="QueryPilot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (connections, schema, query, chat, doctor, memory, evals, glossary):
    app.include_router(module.router)

SAMPLE_CONNECTION_URL = "postgresql://qp_readonly:readonly@localhost:5435/pagila"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "llm": describe_llm(),
        "sampleConnectionUrl": SAMPLE_CONNECTION_URL,
        "allowSampleRows": settings.allow_sample_rows,
        "statementTimeoutMs": settings.statement_timeout_ms,
        "maxResultRows": settings.max_result_rows,
    }
