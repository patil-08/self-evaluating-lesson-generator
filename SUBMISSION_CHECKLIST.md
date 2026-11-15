# Submission checklist

## Assessment requirements

- [x] Agentic LangGraph loop plans, generates, evaluates, routes, retries, and
  ships only when every hard check passes.
- [x] Retry limit is enforced at zero to two regenerations; exhaustion
  escalates with the best draft and a rejection report.
- [x] Versioned hard rubric covers grounding, beginner language, examples,
  jargon, key points, and teaching flow.
- [x] Reports include each attempt, failed check, reason, evidence, fix,
  changes, final status, versions, model labels, tokens, latency, and whether
  execution was mock or live.
- [x] SQLite memory records runs, failure reasons, fix effectiveness, and
  learner feedback; generation reports whether memory influenced a run.
- [x] Prompt evolution is gated on repeated real failures, calibration, and
  improved first-pass rate on real replay. Mock results cannot authorize
  adoption.
- [x] The lesson and learner profile target an Indian beginner with limited
  English vocabulary; the worked example uses a familiar train timetable.
- [x] README, design notes, rubric, source pack, calibration report,
  presentation script, and interview prep are included.

## Verified locally on 2026-11-15

- [x] `python -m pytest -q`: **67 passed**, one third-party LangGraph
  deprecation warning.
- [x] Mock calibration: 12 fixtures, 4/4 known-good lessons passed, 17/17
  expected flaw checks caught, 204/204 exact check outcomes; real calibration
  was skipped.
- [x] Windows end-to-end demo script ran successfully with isolated mock data:
  passing run, feedback, false-claim repair, memory inspection, and ineligible
  mock evolution.
- [x] Bash demo script ran successfully under Git for Windows Bash; a native
  macOS run was not performed.
- [x] `outputs/final/lesson.md` was generated and shipped in **mock** mode.
  Its JSON report identifies `execution_mode: mock`; it is not live-provider
  evidence.
- [x] A false-claim mock run failed `ACC-01` on attempt 1 and passed on attempt
  2. Its report is saved outside the repository in
  `C:\Project 2026\notes\DELIBERATE_ERROR_LOG.md`.
- [x] `.env`, local SQLite data, and generated outputs are ignored by Git.

## Still requires human/provider access

- [ ] A successful live-provider generation and judge run. A live attempt on
  2026-11-15 returned HTTP 400: “Please pass a valid API key.” Verify that
  `LLM_API_KEY` is valid for the configured `LLM_BASE_URL`; do not paste a key
  into chat or commit it. Keep provider settings only in the ignored local
  `.env`.
- [ ] Record and review the 15–20 minute video. The script is prepared, but no
  recording is attached. Keep your face visible and do not show secrets.
- [ ] Upload the GitHub repository, document, and video link to the submission
  portal.
- [ ] Run the Bash demo on macOS/Linux if cross-platform execution needs to be
  demonstrated.

On Windows, run `bash scripts/demo.sh` in a Git Bash terminal. Do not run
`cd "/c/..."` in PowerShell; `/c/...` is Git Bash path syntax. To launch Git
Bash from PowerShell when it is installed in the default location:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' -lc 'cd "/c/Project 2026/lesson-gen/genai-lesson-generator" && bash scripts/demo.sh'
```

To attempt a live run after configuring valid local provider settings, use a
new output directory so the mock artifact remains available for comparison:

```powershell
$env:MOCK_LLM = "0"
python -m lessongen.cli run --topic "Introduction to RAG" --max-retries 2 --out outputs\final-live
```

Inspect the JSON and Markdown rejection reports before presenting any live
result. If the run does not pass, present it as escalated and do not call the
lesson shipped.
