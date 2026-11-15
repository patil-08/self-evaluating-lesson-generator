# Interview prep: project questions and concise answers

1. **What problem does this project solve?**
   **Answer:** It creates a beginner lesson, checks it against mandatory requirements, and
   retries with explicit feedback instead of shipping a failed draft.

2. **Why did you use LangGraph?**
   **Answer:** It makes the plan, generate, evaluate, route, regenerate, ship, and escalation
   steps explicit. The graph state also makes the retry limit testable.

3. **What state does a run keep?**
   **Answer:** It keeps the topic, learner profile, outline, current and best drafts,
   attempt results, rejection log, feedback, memory signals, versions, usage,
   and final status.

4. **How do you know the loop terminates?**
   **Answer:** `MAX_RETRIES` is two. The first draft plus those retries gives at most three
   generation/evaluation attempts; then it ships a pass or escalates.

5. **Why is the rubric binary?**
   **Answer:** Every check describes a required outcome. A high score should not conceal an
   unsupported claim, missing section, or absent limitation.

6. **Why combine code checks and an LLM judge?**
   **Answer:** Code checks handle measurable rules such as length, section order, glossary,
   and word lists. The judge handles semantic coverage, flow, and other jargon.

7. **How do you ground the lesson?**
   **Answer:** The judge receives reviewed facts with IDs and URLs. For accuracy, it must
   extract atomic claims, quote the lesson, cite fact IDs, and mark unsupported
   or contradicted claims as failures.

8. **Does that prove every answer is true?**
   **Answer:** No. The judge is a model, and the fact set is small. This is auditable
   evidence checking, not a formal proof or a guarantee of truth.

9. **What does mock mode test?**
   **Answer:** It provides deterministic generation and judging for offline tests. The
   mock judge catches configured cases; it does not perform the full semantic
   claim audit of a live judge.

10. **How does a retry receive useful feedback?**
    **Answer:** Each failed check includes its reason, evidence quote, and a specific fix
    instruction. The retry keeps useful prior content where possible, and the
    log records before/after changes.

11. **What is stored in memory?**
    **Answer:** SQLite stores run metadata, versions and models, check failures, retry
    instructions and outcomes, and human feedback. It does not store API keys
    or full lesson drafts.

12. **How do you decide a fix worked?**
    **Answer:** Memory counts it as fixed when the same check passes on the immediately
    following attempt after the instruction was sent.

13. **How does self-evolution find a chronic problem?**
    **Answer:** A check must fail in at least three distinct non-mock runs under the same
    rubric. Multiple retries in one run do not count as separate runs.

14. **When can a new prompt become active?**
    **Answer:** Only if calibration remains fully passing and paired real-provider replay
    over at least three distinct RAG topics strictly improves first-pass rate.
    Otherwise the active pointer stays unchanged.

15. **Why can replay use only RAG topics today?**
    **Answer:** The current local facts and rubric are RAG-specific. Replaying a different
    topic against them would not be a valid grounding comparison.

16. **How do you avoid locking the project to one model provider?**
    **Answer:** The client uses an OpenAI-compatible chat-completions API configured by
    environment variables. Generation and judging can use separate model names.

17. **What happens when the API fails or output is malformed?**
    **Answer:** Transient API failures get bounded exponential-backoff retries. Invalid
    structured output and terminal failures are surfaced; they are not treated
    as successful lesson evaluations.

18. **What is a current limitation you would disclose?**
    **Answer:** The mock judge is heuristic, the local sources cover RAG only, and the
    readability rules are rough proxies. This workspace has no live API
    credentials, so the checked-in lesson is explicitly a fallback.

19. **How do you prevent a bad draft from appearing successful?**
    **Answer:** The final lesson field is set only on the ship route after every hard check
    passes. Otherwise the state escalates and the best draft is labeled
    unapproved in the report.

20. **What would you do next for production readiness?**
    **Answer:** Run and review live-provider cases, expand source packs by topic, test
    readability with learners, improve source-level citations, add access
    control cases, and require human approval before adopting prompt changes.
