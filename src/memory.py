"""Persistent memory across runs: which checks fail often, and why."""
import json, os
PATH = os.path.join(os.path.dirname(__file__), "..", "memory.json")

def load():
    if os.path.exists(PATH):
        return json.load(open(PATH))
    return {"runs": 0, "fail_counts": {}, "reasons": {}}

def save(m):
    json.dump(m, open(PATH, "w"), indent=2)

def record_run(failed_results):
    """failed_results: list of {id, reason} from EVERY failed attempt of this run."""
    m = load()
    m["runs"] += 1
    for f in failed_results:
        m["fail_counts"][f["id"]] = m["fail_counts"].get(f["id"], 0) + 1
        m["reasons"].setdefault(f["id"], []).append(f["reason"])
        m["reasons"][f["id"]] = m["reasons"][f["id"]][-5:]  # keep recent
    save(m)

def top_lessons(k=3):
    """Turn the most frequent past failures into short warnings for the generator."""
    m = load()
    ranked = sorted(m["fail_counts"].items(), key=lambda x: -x[1])[:k]
    return [f"Past runs often failed {cid} ({n}x). Example reason: {m['reasons'][cid][-1]}"
            for cid, n in ranked]
