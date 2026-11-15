"""Usage:  python run.py --topic "RAG (Retrieval-Augmented Generation)" [--inject-error]
         python -m src.optimize        # self-evolving step"""
import argparse, json, os, re
from dotenv import load_dotenv
load_dotenv()
from src import graph, memory

ap = argparse.ArgumentParser()
ap.add_argument("--topic", default="RAG (Retrieval-Augmented Generation)")
ap.add_argument("--inject-error", action="store_true", help="demo: corrupt the first draft to show the evaluator catching it")
a = ap.parse_args()

final = graph.build().invoke({"topic": a.topic, "inject_error": a.inject_error})

slug = re.sub(r"\W+", "_", a.topic.lower()).strip("_")[:40]
out = os.path.join("outputs", slug); os.makedirs(out, exist_ok=True)
open(os.path.join(out, "lesson.md"), "w").write(final["lesson"])
json.dump({"topic": a.topic, "status": final["status"], "attempts": final["attempt"], "log": final["log"]},
          open(os.path.join(out, "rejection_log.json"), "w"), indent=2)
failed = [{"id": f["id"], "reason": f["why"]} for e in final["log"] for f in e["failed_checks"]]
memory.record_run(failed)

print(f"\nStatus: {final['status']} after {final['attempt']} attempt(s). Output in {out}/")
for e in final["log"]:
    print(f"  Attempt {e['attempt']}: {'PASS' if e['passed'] else 'FAIL'}", [f['id'] for f in e['failed_checks']])
