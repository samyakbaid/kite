import json
import os
from datetime import datetime, timezone
from pathlib import Path


def empty_state():
    return {"version": 1, "managed_symbols": [], "submissions": []}


def load_state(path):
    path = Path(path)
    if not path.exists():
        return empty_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != 1:
        raise ValueError(f"unsupported state version in {path}")
    if not isinstance(state.get("managed_symbols"), list) or not isinstance(
        state.get("submissions"), list
    ):
        raise ValueError(f"malformed state file: {path}")
    return state


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def already_submitted(state, model, signal_date):
    signal_date = str(signal_date)
    return any(
        item.get("model") == model and item.get("signal_date") == signal_date
        for item in state["submissions"]
    )


def record_submission(state, model, signal_date, results):
    submitted_buys = {
        result["symbol"]
        for result in results
        if result.get("side") == "BUY" and result.get("status") == "submitted"
    }
    state["managed_symbols"] = sorted(set(state["managed_symbols"]).union(submitted_buys))
    state["submissions"].append(
        {
            "model": model,
            "signal_date": str(signal_date),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
    )
    return state
