"""HTTP API for the deployed agent (runs in EKS; also works locally).

POST /investigate   {"question": "...", "session_id": "optional"}   -> report + verdict
GET  /healthz       liveness       GET /readyz   readiness       GET /metrics   Prometheus

Identity of the CALLER: if API_TOKEN is set, a Bearer token is required, and the
X-Requested-By header is written to the audit log (who asked the agent what).
Identity of the AGENT: its Kubernetes ServiceAccount (read-only RBAC) + the least-privilege IAM user
sre-agent-kind (Secret sre-agent-aws) that may only call the approved Claude profile.
"""

from __future__ import annotations

import hmac
import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from app import metrics
from app.agent import investigate
from app.config import load_settings
from app.runtime import Runtime, build_runtime, remember

settings = load_settings()
logging.basicConfig(stream=sys.stdout, level=settings.log_level, format="%(message)s")
audit = logging.getLogger("audit")
STATE: dict[str, Runtime] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    STATE["rt"] = build_runtime(settings)
    yield
    STATE.clear()


app = FastAPI(title="k8s-sre-agent", version="1.0.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


class InvestigateRequest(BaseModel):
    question: str = Field(min_length=5, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, settings.api_token):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if "rt" not in STATE:
        raise HTTPException(status_code=503, detail="starting")
    return {"status": "ready", "env": settings.env, "model": settings.model_id, "guardrail": bool(settings.guardrail_id)}


@app.post("/investigate", dependencies=[Depends(require_token)])
async def investigate_endpoint(req: InvestigateRequest, x_requested_by: str = Header(default="unknown")):
    rt = STATE["rt"]
    result = await run_in_threadpool(
        investigate, rt.agent, req.question, req.session_id, settings.recursion_limit
    )
    metrics.record(result, settings.env)
    remember(rt, req.question, result, x_requested_by)
    audit.info(json.dumps({
        "event": "investigation",
        "env": settings.env,
        "requested_by": x_requested_by[:128],
        "session_id": result.session_id,
        "question": req.question[:300],
        "tools": result.tool_calls,
        "verdict": result.footer,
        "tokens": {"in": result.input_tokens, "out": result.output_tokens},
        "duration_s": result.duration_s,
        "error": result.error,
    }))
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    return result.to_dict()
