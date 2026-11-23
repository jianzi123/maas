AR-R01/R02 implementation closure (PR #18)

Base: 19e43ba980f1bd9f499a92dda435b74b626bf7e9. This patch changes only the
existing Agent Runtime, its regression tests and this note. The original AR-1
OpenAPI, event Schema and AR-B01-B02 files remain byte-for-byte unchanged.

AR-R01: session-document pagination is revision-bound. Signed page payloads
contain both document revision and position, in addition to the existing
principal/authorization revision/path binding. Snapshot messages_next_cursor
and continuation cursors carry the same revision as the returned messages and
resume_cursor. Message, step and tool-call pages reject a changed revision with
410 cursor_expired, snapshot_required=true and retryable=false. Valid old
position-only tokens also require a new snapshot; forged/wrong-scope tokens
remain rejected. The session collection retains its separate keyset paging.

The client must discard all pages and the resume cursor of an invalidated
snapshot, GET the session snapshot again, collect its pages, and replay only
from that snapshot's server-issued resume cursor. It must never POST a new run
as recovery. Any mutation (stream delta, terminal state, rename, edit/new run)
can invalidate document pages. Frequent writes can therefore require another
read after the stream quiets. This deliberately fails closed rather than
retaining unbounded historical snapshots or silently combining watermarks.
GET/reconnect do not persist new snapshots or execute work.

This is the implementation's pagination invalidation choice using existing
410/Error fields; the original architect owns any normative ADR clarification.
It is not a silent edit of the delivered draft.2 contract. Frontend/QA should
explicitly cover MessagePage 410 in addition to the existing event recovery.

AR-R02: limit_reached remains a Run status with duration_limit reason; an
executing safe tool becomes failed, not the run-only limit_reached enum.
The persisted Call records its attempt when dispatch intent is saved. Public
projections retain attempt=1 for executed cancellation/failure and attempt=0
for a tool cancelled before approval/dispatch. Old documents lacking attempt
retain the existing inferred projection for known executing/completed/failed/
unknown states; no old ambiguous cancellation is rewritten or fabricated.
Non-idempotent timeout/cancellation still enters the existing unknown /
needs_confirmation branch before finish; repeated Drive/GET do not re-execute.
No new tool-state enum, accounting writer or migration is introduced.

Validation scope:
- The untouched original review oracle reproduced 2 passing / 2 failing leaf
  cases on the base. Its source and raw log are preserved with the evidence.
- New R01 tests cover 0/98/100/102 historical messages built through normal
  controlled HTTP commands, unchanged page success, stream-delta / completion /
  edit invalidation, fresh snapshot plus replay, Chinese/emoji UTF-8 offset,
  unchanged revision on GET and no extra model execution.
- New R02 tests cover pure/read tools under run duration, independent tool
  timeout and explicit cancellation, approved synthetic write-tool unknown
  barriers and no replay, and never-approved cancellation with attempt zero.
  Public Run, Step, ToolCall and EventPage responses validate against the
  original schema. The synthetic write tool has no external side effect.
- Cursor migration covers unchanged revision, valid legacy token requiring
  snapshot and tampered token rejection.

The first expanded test run intentionally remains archived: the synthetic
write fixture initially tried to disable mandatory approval and was rejected
by the real registry (invalid_input). Only the fixture was corrected to use
the existing approval API; product authorization was not relaxed.

Models, catalog/auth policy and injected tools are controlled adapters;
HTTP handler, service, persistence paths and registry are real implementations.
No SQL, true provider, Higress/Secret, frontend browser or deployment result is
claimed by this patch. Historical SQL and independent QA keep their original
SHA/scope. Final integration must update code first and regenerate its own four
locks; do not copy these locks into the different #16/#17 combination tree.
Rollback preserves sessions/events/attempts, child request references and
unknown/held state, stops new dispatch and never replays uncertain execution.