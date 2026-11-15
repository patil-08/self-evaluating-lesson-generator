"""Two-layer evaluator: deterministic code checks + LLM judge. All checks are strictly pass/fail."""
import re, yaml, os
from . import llm

RUBRIC = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "rubric.yaml")))["checks"]
JARGON = ["embedding", "vector database", "llm", "large language model", "hallucination",
          "retrieval", "prompt", "chunk", "knowledge base", "token", "weights"]
DEFINE_HINTS = ["means", "is a ", "is an ", "is the ", "are ", "stands for", "called", "(", "—", ":", "is when", "this is"]
REQUIRED = ["what is", "why", "how", "example", "recap"]

def _sentences(text):
    body = re.sub(r"^#+.*$", "", text, flags=re.M)
    return [s for s in re.split(r"(?<=[.!?])\s+", body) if len(s.split()) > 2]

def code_checks(lesson):
    out = {}
    heads = [h.lower() for h in re.findall(r"^#+\s*(.+)$", lesson, flags=re.M)]
    missing = [r for r in REQUIRED if not any(r in h for h in heads)]
    out["C1_sections"] = (not missing, f"Missing sections: {missing}" if missing else "ok")

    sents = _sentences(lesson)
    avg = sum(len(s.split()) for s in sents) / max(1, len(sents))
    out["C2_sentence_length"] = (avg <= 16, f"Average sentence length is {avg:.1f} words (limit 16)")

    low, bad = lesson.lower(), []
    for term in JARGON:
        i = low.find(term)
        if i == -1:
            continue
        window = low[max(0, i - 80): i + 220]
        if not any(h in window for h in DEFINE_HINTS):
            bad.append(term)
    out["C3_jargon_defined"] = (not bad, f"Terms not explained near first use: {bad}" if bad else "ok")

    n = len(lesson.split())
    out["C4_length"] = (500 <= n <= 1100, f"Word count is {n} (allowed 500-1100)")
    return out

def llm_checks(lesson, sources):
    qs = [c for c in RUBRIC if c["type"] == "llm"]
    qtext = "\n".join(f'- {c["id"]}: {c["question"]}' for c in qs)
    prompt = f"""You are a STRICT reviewer of beginner lessons. Judge the LESSON against each check.
Rules: answer pass=true ONLY if the check is clearly satisfied. No partial credit. If unsure, fail it.
For L5_accurate, compare every factual claim to the SOURCES; any unsupported or false claim = fail.
Give a one-sentence reason for each (for fails: say exactly what is wrong and how to fix it).

CHECKS:
{qtext}

SOURCES:
{sources}

LESSON:
{lesson}

Return ONLY JSON: {{"<check_id>": {{"pass": true/false, "reason": "..."}}, ...}}"""
    data = llm.parse_json(llm.chat(prompt, model_env="JUDGE_MODEL", json_mode=True, temperature=0))
    return {c["id"]: (bool(data[c["id"]]["pass"]), data[c["id"]]["reason"]) for c in qs}

def evaluate(lesson, sources):
    merged = {**code_checks(lesson), **llm_checks(lesson, sources)}
    return [{"id": cid, "passed": ok, "reason": why} for cid, (ok, why) in merged.items()]
