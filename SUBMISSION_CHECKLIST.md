# Submission checklist

## Implementation and documentation

- [x] LangGraph generation/evaluation loop has a hard maximum of two retries.
- [x] Rubric is versioned and all checks are hard pass/fail.
- [x] Sources, mock mode, persistent memory, and evidence-gated evolution are
  documented.
- [x] Windows and macOS/Linux setup and demo scripts are present.
- [x] README, design notes, calibration report, Loom script, and interview prep
  are present.
- [x] `FINAL_LESSON.md` contains a plain-language RAG lesson, passes the local
  mock rubric, and explicitly labels its fallback status.
- [ ] Replace the fallback lesson with one from a real-provider run, after
  configuring live credentials privately and confirming all checks pass.
- [ ] Record and review the 15–20 minute Loom; keep your face visible and do
  not show `.env` or other secrets.
- [ ] Upload the repository and Loom link to the submission portal.

## Validation before submission

- [x] Full pytest suite passes: `python -m pytest -q` — 50 passed.
- [x] Mock calibration report shows 4/4 good lessons pass and 17/17 expected
  flaw checks caught.
- [x] Ordered PowerShell and Bash demo scripts were run with isolated mock data
  and did not call a live provider.
- [ ] After a live run, inspect the saved JSON/Markdown report and rejection
  log; do not claim a real run if mock mode was active.
- [x] Confirm `.env`, API keys, and personal data are not staged or committed.
- [x] Verify `git status` is clean after the Step 9 commit.

## Current blocker

The current environment reports `live_credentials_ready=False`. Do not paste a
key into this repository or into chat. Configure the provider values in a local,
ignored `.env` file, set `MOCK_LLM=0`, then run:

```powershell
python -m src.cli run --topic "Introduction to RAG" --max-retries 2
```

Only replace the fallback lesson after that command returns `passed` and the
real-provider report has been reviewed.
