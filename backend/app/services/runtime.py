"""Install a loaded model store into the running API (used at startup and after an artifact upload)."""
from __future__ import annotations

import threading

from ..api.deps import STATE
from .store import Store

_lock = threading.Lock()


def install_store(store: Store) -> None:
    from .replay import ReplayEngine
    from .seed import seed_reference
    with _lock:
        old = STATE.get("replay")
        if old is not None:
            try:
                old.stop()
            except Exception:  # pragma: no cover
                pass
        seed_reference(store)
        engine = ReplayEngine(store)
        engine._reset(None)                    # replay alerts belong to a replay session; start clean (state: IDLE)
        engine.processed.clear()
        STATE["store"] = store
        STATE["replay"] = engine

    def warm():                                # pre-compute explanations for flagged hours so first page loads are fast
        for r in store.scored[store.scored.risk_score > 30].itertuples():
            try:
                store.explain(store.by_sheet[r.substation]["id"], r.timestamp)
            except Exception:  # pragma: no cover
                pass
    threading.Thread(target=warm, daemon=True).start()
