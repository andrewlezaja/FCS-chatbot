# Roadmap and known limitations

Ordered roughly by value for effort.

## Testing and evaluation

1. **Automate eval scoring.** Today `eval.py` writes transcripts for manual review. Split each case into:
   - *deterministic checks*: which tools must or must not be called, and strings that must or must not appear (for example, A5's answer must start with a safety instruction, and C4 must not contain a duration like "3 hours");
   - an *LLM-as-judge* rubric for the rest, graded against the case's `note`.

   Then report a pass rate and fail the run on regressions. That turns "re-run the eval after prompt changes" into a CI gate.
2. **Unit tests for the deterministic layer**, run against `db/demo.db` with no API calls: `_build_fts_query` (operators and empty input), `get_work_orders` truncation math and the `COALESCE` date, `_delete_not_in`'s empty-fetch guard, `_reset_wait` header parsing, and `sync_manuals`' three-state skip logic. These are fast and free, so they can run on every commit.
3. **Run each eval case several times.** LLM output varies between runs, so a single pass can hide a case that fails 1 time in 5.
4. **Grow the eval set from real usage** (see logging below), especially from questions people asked that the bot handled badly.

## Retrieval quality

5. **Multi-term keyword search for work orders.** `get_work_orders` matches one substring, so "comm error" only finds "DeviceNet" because the model thinks to retry with other words. An FTS5 index over work order titles and descriptions, like the one manuals already have, would make recall depend less on the model's guessing.
6. **OCR for scanned manuals.** Image-only PDFs (most part drawings) are currently invisible to search. Run OCR on attachments with `extracted = 2`, or use Claude's PDF and vision input on them.
7. **Hybrid search once volume grows.** Add embeddings alongside BM25 when work orders reach the high hundreds.

## Prompt and data hygiene

8. **Move dataset facts out of the prompt.** The prompt says "about 60% of work orders have an Actual Completion Date". That was true when written, but the current data is 100%. Facts like that go stale silently. Have a tool report them (for example, date-confirmation coverage in `get_reliability_stats`) and keep the prompt to rules only.
9. **Fix category data upstream.** In production every work order is categorized "Invoice", so "which machine has the most electrical issues?" has to be inferred from asset names like "Electrical Cabinet (M3)". Proper tagging in MaintainX, or a classification pass during sync, would make `category` filtering useful.
10. **Small known staleness:** the `get_work_orders` `order` parameter is described as "Order by completed_at" but the SQL sorts by `service_date`. Some eval notes reference counts from an older snapshot (C3's "17 WOs", A4's "5 known assets").

## Product and operations

11. **Stream responses.** Answers that take several tool calls can take 10+ seconds. Streaming the final answer (`st.write_stream`) and showing which tool is running would make the wait feel shorter.
12. **Usage logging and feedback.** Log questions, tool calls, answers and a 👍/👎 to find real failure cases. Today there's no record of how the bot is used.
13. **Per-session cost tracking.** `USAGE` is process-global, so the sidebar's "Session usage" actually totals every session on the server. Keep it in `st.session_state`, or relabel it.
14. **Cache the conversation, not just the system prompt.** Each loop iteration resends the whole growing history at full price. A `cache_control` breakpoint on the latest message would bill the repeated history at the cache rate. Large tool results (up to 500 work orders) could also be trimmed from older turns.
15. **Guard the full refresh.** Two users clicking "Full refresh" at once would run two syncs against the same file. A process-level lock (or disabling the button while a refresh is running) would prevent that.
16. **Detect changed manuals.** Extraction is keyed by attachment id, so a re-uploaded manual with the same id is never re-extracted. Store a content hash or `updatedAt` and re-extract when it changes.
17. **Pin dependency versions** in `requirements.txt` so the cloud build is reproducible.
18. **Access control.** The production app exposes internal maintenance data. Make sure the Streamlit Community Cloud app is restricted to invited viewers (or put it behind SSO) rather than public.
