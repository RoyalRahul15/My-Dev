# Customer 360 — Conversational AI Service

A production-grade conversational agent that answers customer questions by
**routing** each message to the right handler:

| Question type | Route | Handler |
|---------------|-------|---------|
| "What is my portfolio value?" | **DATA** | SQL agent → queries the warehouse (read-only, scoped to the caller) |
| "What is the exit-load policy?" | **POLICY** | RAG agent → retrieves from policy docs, answers with citations |
| "Hi, what can you do?" | **CHAT** | Chat agent → plain LLM conversation |

Every message passes through **guardrails** on the way in and out, and every
model call goes through a single **LLM gateway**.

## Request lifecycle

```
customer message
   │
   ▼
Input Guardrail ─── blocked? → safe refusal
   │  (injection, exfiltration, length)
   ▼
Intent Router ──→ DATA │ POLICY │ CHAT
   │                 │      │       │
   │            SQL Agent  RAG    Chat Agent
   │           (scoped,   Agent   (LLM only)
   │            read-only) (cited)
   ▼
Output Guardrail ── PII redaction + advice disclaimer
   │
   ▼
answer + intent + citations
```

## Components

| Path | Purpose |
|------|---------|
| `gateway/llm_gateway.py` | One entry point for all LLM calls — retry, fallback, caching, token accounting; pluggable providers |
| `guardrails/guardrails.py` | Input (injection, exfiltration) + output (PII redaction, advice disclaimer) |
| `router/intent_router.py` | Rule-first, LLM-fallback intent classification |
| `agents/sql_agent.py` | Text-to-SQL — **read-only, single-statement, mandatory customer scope, row cap, table whitelist** |
| `agents/rag_agent.py` | Retrieval-grounded answers with citations; declines when nothing clears the threshold |
| `agents/chat_agent.py` | Scoped general conversation |
| `agents/conversation_orchestrator.py` | Ties guardrails + router + agents + memory together |
| `memory/conversation_memory.py` | Per-session short-term memory (swap for Redis in prod) |
| `service/app.py` | FastAPI `/chat`, `/health`, `/ready`; bearer-auth resolves the customer server-side |

## Security guarantees

- **No cross-customer reads** — `serial_no` comes from the authenticated token, never the client; the SQL validator refuses any query not scoped to it.
- **Read-only SQL** — only `SELECT`; DDL/DML/multi-statement is rejected before execution.
- **Grounded policy answers** — RAG answers strictly from retrieved passages, with citations; declines rather than hallucinating.
- **PII never leaks** — output guardrail redacts PAN, Aadhaar, email, phone.
- **Injection & exfiltration blocked** at the input guardrail.

## Run

```bash
pip install -r requirements.txt
export CAI_LLM_API_KEY="..."          # provider key
export CAI_ODBC_DSN="DSN=impala_ro"   # read-only DB user
uvicorn conversational_ai.service.app:app --host 0.0.0.0 --port 8080
```

Wire the retriever + read-only query runner at startup via
`service.app.build_orchestrator(retriever=..., query_runner=...)`.

## Test (no API key / DB needed)

```bash
PYTHONPATH=. python conversational_ai/smoke_test.py
```

Exercises routing, SQL scoping, RAG grounding, and both guardrails with fakes.
