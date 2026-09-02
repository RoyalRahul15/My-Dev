# Serving Layer — the Batch-to-Live Bridge

Closes the gap between the **offline batch plane** (feature engineering, model
training, segmentation — heavy, all customers, runs nightly) and the **online
serving plane** (a live customer question, one customer, answered in
milliseconds).

The customer **never touches the analytical warehouse**. The batch job
publishes its results here; the conversational agent reads from here.

## The two planes

```
OFFLINE / BATCH                         ONLINE / SERVING
Impala warehouse                        Redis / online store
   ↓ nightly                                ↑ millisecond lookup
feature engineering → master_df             │
   ↓                                        │
model scoring + segmentation                │
   ↓                                        │
Publisher.publish()  ───────────────────────┘
```

## Components

| File | Purpose |
|------|---------|
| `online_store.py` | `OnlineStore` interface + `InMemoryOnlineStore` (dev) and `RedisOnlineStore` (prod) |
| `publisher.py` | End-of-batch step: merges features + scores + segments, writes one record per customer |
| `feature_lookup.py` | Live DATA handler: key lookup + LLM summarisation — no warehouse on the request path |

## Why this exists

| | Batch plane | Serving plane |
|--|------------|---------------|
| Store | Impala (analytical) | Redis / online store |
| Scope | All 553K customers | One customer |
| Speed | Minutes | Milliseconds |
| Access | Full scans + joins | Single key lookup |
| Refreshed | Nightly | Read live |

Running a batch pipeline for one live question is impossible; an analytical
warehouse is the wrong store for single-row lookups. The serving layer holds a
fast, pre-computed copy of the results so the agent can answer instantly.

## Usage

```python
# End of the nightly batch job
from serving import InMemoryOnlineStore, Publisher   # or RedisOnlineStore
store = RedisOnlineStore(url="redis://…")
Publisher(store).publish(master_df, scores=scores, segments=segments, ttl_s=86400)

# Live, inside the conversational agent's DATA path
from serving import FeatureLookupAgent
agent = FeatureLookupAgent(store, summariser=llm_gateway)
answer = agent.answer("What is my portfolio value?", serial_no=authenticated_id)
```

## Freshness note

- **Pre-computed questions** ("my portfolio value", "my segment", "my propensity") → this online store.
- **Fresh operational questions** ("did my SIP debit today?") → a separate SQL agent over an operational **read-replica**, never the analytical warehouse.

## Test

```bash
PYTHONPATH=. python serving/smoke_test.py
```
