# Customer 360 — Multi-Agent Propensity Pipeline

Production-grade multi-agent system that turns raw customer data into a merged
feature table, propensity scores, and next-best-product recommendations.

Each product line is handled by its own **feature agent**; an **orchestrator**
runs them in parallel with per-agent fault isolation, then chains
**merge → score → recommend**.

## Architecture

```
Orchestrator
  ├── Feature Agents (parallel, one connection each)
  │     ├── CIBIL          → cibil credit features
  │     ├── Adobe Campaign → email engagement features
  │     └── … (MF, Equity, F&O, IPO — drop-in registry)
  ├── Merge Agent      → left-join all frames onto Customer 360 anchor
  ├── Scoring Agent    → propensity_<product> (any predict_proba model)
  └── Recommendation Agent → next-best product (cosine similarity)
```

## Layout

| Path | Purpose |
|------|---------|
| `config/settings.py` | Env-driven settings, resolved once at startup |
| `utils/db.py` | `run_query` (no `pd.read_sql`), `ConnectionFactory`, retry-with-backoff |
| `utils/logger.py` | Uniform structured logging |
| `agents/base.py` | `Agent` contract + `AgentResult` (failures never crash a batch) |
| `agents/feature_agents.py` | One agent per product + the registry |
| `agents/merge_agent.py` | Consolidates onto the customer anchor |
| `agents/scoring_agent.py` | Applies a versioned propensity model |
| `agents/recommendation_agent.py` | Collaborative filtering (numpy only) |
| `agents/orchestrator.py` | Parallel execution + pipeline chaining |
| `sql/builders.py` | One SQL builder per product (optimised) |
| `main.py` | Entry point |

## Configuration

All via environment variables — nothing secret in source:

| Variable | Default | Meaning |
|----------|---------|---------|
| `C360_ODBC_DSN` | *(required)* | pyodbc DSN / connection string |
| `C360_DB_SCHEMA` | `iservedb` | Impala schema |
| `C360_AS_OF_DATE` | `2024-12-31` | Feature as-of date |
| `C360_MIN_DATE` | `2022-01-01` | Lookback start |
| `C360_MAX_WORKERS` | `6` | Parallel feature agents |
| `C360_MAX_RETRIES` | `3` | Retries on transient DB errors |
| `C360_MODEL_DIR` | `./models` | Trained model artifacts |
| `C360_OUTPUT_DIR` | `./output` | Output location |

## Run

```bash
pip install -r requirements.txt
export C360_ODBC_DSN="DSN=your_impala_dsn"
python -m customer360_agents.main
```

## Add a new product

1. Write its SQL builder in `sql/builders.py` (return SQL keyed on `serial_no`).
2. Register it in `FEATURE_REGISTRY` in `agents/feature_agents.py`.

That's it — the orchestrator picks it up automatically and runs it in parallel.

## Design guarantees

- **Fault isolation** — one product's failure is logged and skipped; the run continues.
- **Thread safety** — every parallel agent opens its own connection (pyodbc is not thread-safe).
- **No customer loss** — merge always left-joins onto the full Customer 360 anchor.
- **Model-agnostic scoring** — any estimator with `predict_proba` (LogReg / RF / XGBoost).
