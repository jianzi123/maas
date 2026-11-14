R5 separates a visible, known rollback conflict from an unavailable dependency.
It extends PR #6, preserving the 0559 local service and the subsequent b07f2ab /
f445362 workbench/identity assembly commits, and preserves
the R1–R3 closure at ac94/50354a7. No schema, public error code, DDL or ledger
format changes are needed.

| Condition after namespace and original-domain checks | HTTP |
| --- | --- |
| Known legacy revision without a private snapshot; pruning/unavailable retention; confirmed blocked lifecycle; incompatible rollback spec | 409, existing resource_version_conflict |
| Invisible domain, absent history directory or unknown revision | 404 |
| Missing/closed payload connection, missing registry/evaluator, missing retention metadata, corrupt retained bytes, unknown or malformed evaluation, state/pricing unavailable | 503 |
| Malformed input | 400 |

`LoadSpec` uses a left retention join: a missing retention record is not treated
as proof that a known snapshot was pruned. Original-domain checks precede the
revision lookup; no revision existence is disclosed across domains. Retained
payload hashes and revision input remain mandatory.

`RollbackService.Prepare` performs only reads, including the final UID/RV check.
Management performs this preflight before creating the durable operation. A
successful dispatch performs one update of the prepared CR with its original
UID/resourceVersion. API-server CAS protects concurrent changes after preflight;
such dispatched races can leave a failed/unknown operation as before. The
no-write guarantee applies to preflight rejections, not to writes already
dispatched with an unknown ACK. Queries never replay them or infer their ACK
from the current CR.

Run the targeted checks using existing approved portable tools:

```sh
MAAS_R5_TOOL_ROOT=/path/to/existing/task/.cache bash scripts/test-r5.sh
```

The script copies dependency inputs into its own task cache, starts a private
socket-only MySQL and temporary envtest API-server, and cleans its processes
and data on exit. It runs only the create/history setup and R5 matrix, then
affected package tests/vet and command builds. HTTP evidence is written to
`artifacts/r5-http.json`; raw results to `artifacts/r5-targeted.txt`.

These are controlled SQL/HTTP/CR results with metadata resolver fixtures,
not real Higress/model, production-role or A01–A34 acceptance. Final product
and deployment locks must be refreshed only after the exact reviewed heads
and independent results are fixed. Existing running workbenches are untouched.

Author validation used Go 1.26.0, MySQL 8.4.7 and the existing envtest binaries
in Ubuntu-22.04 WSL. R5 passed 19/19 leaf cases (18 rejections plus one restored
dispatch/query control), with a separate create/history setup case passing.
The rejected requests left CR resourceVersion, API mutation count, operation
count and generation/usage/budget ledgers unchanged. The restored request
created exactly one operation and one API update; two original-operation
queries did not replay it. The retained corruption and missing-retention
controls remained 503. This is author evidence awaiting independent QA.

Affected history and controlapi package tests passed. The management package
has no standalone tests; it is exercised by the actual HTTP integration above
and is not counted as another passing test suite. R1–R3 and D1 were not rerun.
