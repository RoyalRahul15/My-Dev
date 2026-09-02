"""Smoke test — proves the batch-to-serving bridge end to end.

1. Simulate batch outputs (master features + scores + segments).
2. Publish them to the online store (the last batch step).
3. Serve a live customer question with a millisecond key lookup — no warehouse.
"""
from __future__ import annotations

import pandas as pd

from serving.feature_lookup import FeatureLookupAgent
from serving.online_store import InMemoryOnlineStore
from serving.publisher import Publisher


class FakeSummariser:
    """Stands in for the LLM gateway — echoes the value it was given."""

    def complete(self, *, system, prompt, max_tokens):
        class R:
            text = f"Based on your file: {prompt.split('Your data:')[-1][:80]}"
        return R()


def main() -> None:
    # 1. Simulated batch outputs -----------------------------------------
    master = pd.DataFrame({
        "serial_no": ["9001052421", "9001314742"],
        "mf_portfolio_value": [125000.0, 4000.0],
        "days_since_any_activity": [12, 300],
    })
    scores = {
        "gold_fund": pd.DataFrame({
            "serial_no": ["9001052421", "9001314742"],
            "propensity_gold_fund": [0.87, 0.11],
        })
    }
    segments = pd.DataFrame({
        "serial_no": ["9001052421", "9001314742"],
        "segment": ["High-Value Active Trader", "Dormant"],
    })

    # 2. Publish (end of nightly batch) ----------------------------------
    store = InMemoryOnlineStore()
    published = Publisher(store).publish(master, scores=scores, segments=segments, ttl_s=86400)
    assert published == 2
    print(f"published {published} records; store size = {len(store)}")

    # 3. Serve live ------------------------------------------------------
    agent = FeatureLookupAgent(store, FakeSummariser())

    ans = agent.answer("What is my portfolio value?", serial_no="9001052421")
    assert ans.found
    assert "propensity_gold_fund" in ans.fields_used
    assert "segment" in ans.fields_used
    print("LIVE LOOKUP  ->", ans.answer)
    print("fields served:", ans.fields_used)

    # Unknown customer degrades gracefully.
    missing = agent.answer("What is my portfolio value?", serial_no="0000000000")
    assert not missing.found
    print("UNKNOWN CUST ->", missing.answer)

    print(f"\nstore stats: reads={store.stats.reads} writes={store.stats.writes} "
          f"misses={store.stats.misses}")
    print("BATCH -> SERVING BRIDGE SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
