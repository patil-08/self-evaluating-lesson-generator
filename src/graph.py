"""LangGraph workflow: plan -> generate -> evaluate -> (ship | retry | flag for human)."""
import glob, os
from typing import TypedDict
from langgraph.graph import StateGraph, END
from . import llm, memory, evaluator

MAX_RETRIES = 2
ROOT = os.path.join(os.path.dirname(__file__), "..")
AUDIENCE = ("a 12th-grade graduate from India, limited English vocabulary, non-English-medium "
            "background, zero technical background, wants to start an AI career")

class S(TypedDict, total=False):
    topic: str; sources: str; outline: str; lesson: str
    attempt: int; results: list; log: list; status: str; inject_error: bool

def _latest_guidelines():
    files = sorted(glob.glob(os.path.join(ROOT, "prompts", "generator_guidelines_v*.txt")),
                   key=lambda p: int(p.rsplit("_v", 1)[1].split(".")[0]))
    return open(files[-1]).read(), os.path.basename(files[-1])

def plan(s: S):
    sources = "\n".join(open(p).read() for p in glob.glob(os.path.join(ROOT, "sources", "*.md")))
    outline = llm.chat(f"Create a short lesson outline (bullet points) on '{s['topic']}' for {AUDIENCE}. "
                       f"Order: what it is, why it matters, how it works (steps), one example, limitations, recap. "
                       f"Use ONLY these sources:\n{sources}")
    return {"sources": sources, "outline": outline, "attempt": 0, "log": []}

def generate(s: S):
    attempt = s["attempt"] + 1
    guidelines, gv = _latest_guidelines()
    warnings = memory.top_lessons()
    feedback = ""
    if s.get("results"):
        fails = [r for r in s["results"] if not r["passed"]]
        feedback = "FIX THESE PROBLEMS FROM THE LAST DRAFT:\n" + "\n".join(f'- {r["id"]}: {r["reason"]}' for r in fails)
    prompt = f"""Write a standalone beginner lesson on "{s['topic']}" for {AUDIENCE}.
OUTLINE:\n{s['outline']}\n\nSOURCES (only use facts from here):\n{s['sources']}\n
GUIDELINES ({gv}):\n{guidelines}\n
LESSONS FROM PAST RUNS (avoid repeating):\n{chr(10).join(warnings) or 'none yet'}\n
{feedback}
Return only the lesson in Markdown."""
    lesson = llm.chat(prompt, temperature=0.5)

    log = list(s["log"])
    if attempt > 1:  # record what changed on retry
        summary = llm.chat(f"In 2 short sentences, say what changed between DRAFT A and DRAFT B.\n\nDRAFT A:\n{s['lesson']}\n\nDRAFT B:\n{lesson}", temperature=0)
        log[-1]["what_changed_on_retry"] = summary

    if s.get("inject_error") and attempt == 1:  # demo: deliberately break the lesson
        lesson += ("\n\n## How does RAG work? (extra)\nRAG works by retraining the model's weights on your files "
                   "every time you ask. It uses HNSW-indexed dense cosine retrieval over BM25 sparse tokens.")
    return {"lesson": lesson, "attempt": attempt, "log": log}

def evaluate(s: S):
    results = evaluator.evaluate(s["lesson"], s["sources"])
    failed = [r for r in results if not r["passed"]]
    log = list(s["log"]) + [{"attempt": s["attempt"], "passed": not failed,
                             "failed_checks": [{"id": r["id"], "why": r["reason"]} for r in failed]}]
    return {"results": results, "log": log}

def route(s: S):
    if all(r["passed"] for r in s["results"]):
        return "ship"
    return "generate" if s["attempt"] <= MAX_RETRIES else "flag"

def ship(s: S): return {"status": "SHIPPED"}
def flag(s: S): return {"status": "FLAGGED_FOR_HUMAN_REVIEW"}

def build():
    g = StateGraph(S)
    for name, fn in [("plan", plan), ("generate", generate), ("evaluate", evaluate), ("ship", ship), ("flag", flag)]:
        g.add_node(name, fn)
    g.set_entry_point("plan")
    g.add_edge("plan", "generate"); g.add_edge("generate", "evaluate")
    g.add_conditional_edges("evaluate", route, {"ship": "ship", "generate": "generate", "flag": "flag"})
    g.add_edge("ship", END); g.add_edge("flag", END)
    return g.compile()
