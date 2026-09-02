"""FastAPI serving layer — the customer-facing entry point.

Exposes a single ``/chat`` endpoint behind bearer-token auth. The authenticated
identity determines ``serial_no`` server-side — the client never supplies which
customer's data to read, closing the cross-customer access hole. Health and
readiness probes support Kubernetes.

Run:  uvicorn conversational_ai.service.app:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

from typing import Optional

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from pydantic import BaseModel, Field
except ImportError as err:  # pragma: no cover
    raise RuntimeError("Install fastapi and pydantic to run the service.") from err

from ..agents.conversation_orchestrator import ConversationOrchestrator
from ..config.logger import get_logger
from ..config.settings import settings
from ..gateway.llm_gateway import LLMGateway

log = get_logger("service")

app = FastAPI(title="Customer 360 Conversational Assistant", version="1.0.0")

# Wired at startup (see build_orchestrator). In real deployment these come from
# the DI container: a live vector retriever and a read-only DB query runner.
_orchestrator: Optional[ConversationOrchestrator] = None


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    intent: str
    citations: list[str] = []
    flags: list[str] = []


def resolve_customer(authorization: str = Header(...)) -> str:
    """Resolve the authenticated customer's serial_no from the bearer token.

    Replace the body with real token verification (JWT/OAuth introspection).
    The key property: the *server* decides whose data is accessible, not the
    client payload.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    serial_no = _verify_token_and_get_serial(token)
    if not serial_no:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return serial_no


def _verify_token_and_get_serial(token: str) -> Optional[str]:
    # Placeholder for JWT verification + claim extraction.
    # e.g. claims = jwt.decode(token, KEY, algorithms=["RS256"]); return claims["serial_no"]
    return token or None


def get_orchestrator() -> ConversationOrchestrator:
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return _orchestrator


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    return {"ready": _orchestrator is not None}


@app.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    serial_no: str = Depends(resolve_customer),
    orch: ConversationOrchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    reply = orch.handle(session_id=req.session_id, serial_no=serial_no, message=req.message)
    return ChatResponse(
        reply=reply.text, intent=reply.intent,
        citations=reply.citations, flags=reply.flags,
    )


def build_orchestrator(*, retriever, query_runner) -> ConversationOrchestrator:
    """Construct and install the orchestrator (call once at startup)."""
    global _orchestrator
    settings.validate()
    gateway = LLMGateway(cfg=settings)
    _orchestrator = ConversationOrchestrator(
        gateway=gateway, retriever=retriever, query_runner=query_runner
    )
    log.info("orchestrator ready")
    return _orchestrator
