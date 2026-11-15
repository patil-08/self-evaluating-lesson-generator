# Loom walkthrough script (18 minutes)

## Before recording

- Keep the webcam on with your face visible throughout the walkthrough.
- Share the project window, not the `.env` file or environment variables.
- This workspace has no live LLM credentials configured. Say plainly that this
  run uses deterministic mock mode; do not describe it as a live model run.
- Start in the repository root. The following Windows commands use an isolated
  demo database under `outputs/`.
- Activate the virtual environment first:
  `.\.venv\Scripts\Activate.ps1` on Windows or `. .venv/bin/activate` on
  macOS/Linux.
- The complete ordered sequence is also available as
  `.\scripts\demo.ps1` (Windows) or `bash scripts/demo.sh` (macOS/Linux).

## 0:00-3:00 — Face introduction and architecture (3 minutes)

**0:00-1:00 — Face visible, introduce the project**

Say: “Hi, I’m Mansi Patil. This is my beginner lesson generator for a learner
starting an AI career. It writes a lesson, checks every required condition, and
only returns it as approved if every hard check passes.”

**1:00-2:00 — Explain the learner and rubric**

Show the learner profile and `rubric/v1.yaml`. Explain that short sentences,
plain vocabulary, a glossary, a familiar example, grounded claims, and a
limitation are required. No partial score can hide a failed check.

**2:00-3:00 — Explain the architecture**

Show the Mermaid diagram in `README.md` or `docs/DESIGN.md`. Trace plan →
generate → evaluate → route. A failed draft gets evidence and a fix instruction.
The initial draft plus two retries gives a maximum of three attempts; then the
graph escalates rather than shipping a failed lesson.

## 3:00-8:00 — End-to-end normal run (5 minutes)

**3:00-4:00 — Set up the deterministic demonstration**

In PowerShell, run:

```powershell
$env:MOCK_LLM = "1"
```

Say: “I’m choosing offline mock mode so the recording is reproducible and does
not expose credentials. The command path and evaluator are the same; the model
responses are canned.”

**4:00-5:00 — Start the normal lesson run**

```powershell
python -m src.cli run --topic "Introduction to RAG" --mock --output-dir outputs\demo_runs --memory-db outputs\demo_memory.sqlite3
```

**5:00-7:00 — Walk through the result**

Point out the status, run ID, model labels, report paths, and memory signals.
Show the lesson sections and the rejection log. A clean run should say “No
rejected drafts.” Explain that the Markdown and JSON reports preserve the
attempt history and rubric version.

**7:00-8:00 — Set up the evaluator demonstration**

Explain that the next command adds one deliberate jargon error to the first
draft. The expected behavior is rejection followed by a corrected retry, not
silently accepting the draft.

## 8:00-12:00 — Evaluator catches a deliberate error (4 minutes)

**8:00-9:00 — Run with a deliberate flaw**

```powershell
python -m src.cli run --topic "Introduction to RAG" --inject-error jargon --max-retries 2 --mock --output-dir outputs\demo_runs --memory-db outputs\demo_memory.sqlite3
```

**9:00-10:00 — Show the rejection**

Read the failed check ID, why it failed, the evidence quote, and the explicit
fix instruction. The injected phrase is an unsupported technical claim, so the
accuracy and jargon checks reject it.

**10:00-11:00 — Show what changed**

Point to the retry-change summary in the console and the Markdown report in
`outputs\demo_runs`. Explain that it records removed and added text rather
than merely saying “fixed.”

**11:00-12:00 — Show the final route**

The retry passes and the status is `passed`. Explain that if it had failed
again twice, the status would be `escalated_to_human` and the best draft would
remain explicitly unapproved.

## 12:00-15:00 — Memory and self-evolution (3 minutes)

**12:00-13:00 — Display memory**

```powershell
python -m src.cli memory --memory-db outputs\demo_memory.sqlite3
```

Point out run history, per-check failure counts, and which fix worked on the
next attempt. Explain that memory is SQLite-backed and the generator receives
only a capped advisory summary.

**13:00-14:00 — Explain the evolution gate**

Say: “One injected mock failure is not enough to change a prompt. Evolution
requires the same check to fail in three distinct real runs under the same
rubric.”

**14:00-15:00 — Run evolution**

```powershell
python -m src.cli evolve --memory-db outputs\demo_memory.sqlite3 --report outputs\demo_evolution_report.md --changelog outputs\demo_CHANGELOG.md
```

Open the report. In this isolated mock demonstration, expect no candidate and
no adoption. Mock data is labeled, and cannot meet the real-run threshold.

## 15:00-18:00 — Trade-offs, limitations, and next steps (3 minutes)

**15:00-16:00 — Trade-offs**

Explain the hybrid evaluator: code checks make measurable rules repeatable;
the semantic judge handles meaning and flow. A single judge keeps this
take-home small, but it can still be wrong. Binary checks favor clear
acceptance over a misleading average score.

**16:00-17:00 — Limitations and honest run status**

The current source collection is about RAG, not arbitrary AI topics. The mock
judge is a deterministic heuristic, not a substitute for full semantic
verification. This environment has no live credentials, so the checked-in
`FINAL_LESSON.md` is explicitly marked as a mock-checked fallback. Do not claim
that a live generation or real-model judgment happened.

**17:00-18:00 — Next steps and close**

Show the test command and current result:

```powershell
python -m pytest -q
```

Say that the next validation step is to configure credentials privately, run
the live generation and judge, inspect the rejection log, and replace the
fallback lesson only after a real passing run. Keep your face visible through
the closing sentence.

## macOS/Linux command equivalents

The demo script runs the same sequence:

```sh
bash scripts/demo.sh
```

For manual recording, replace `outputs\...` in the four PowerShell commands
above with `outputs/...`. Do not remove `--mock` unless live credentials have
been configured and the recording is intentionally showing a real-provider
run.
