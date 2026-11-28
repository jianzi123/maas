# Protected tools-v1 adapter

This increment starts at unified merge `4402c456a155646ee4111e5f4a1f285621c11273`, which contains the original Agent core, product/MySQL entry and controlled offline profile. It extends those components. Public AR-1 draft.2, event 1.0, admission ticket v3 and terminal 3.0 remain the existing contracts.

## Configuration and capability

The normal `maas-service serve --config FILE` consumes the following **example fields**, together with the existing private gateway TLS, signing key, timeouts, budgets and mounted platform Key. They do not install a publication or approve a provider:

```json
{
  "alias": "installation-approved-alias",
  "publication_id": "00000000-0000-4000-8000-000000000001",
  "platform_key_file": "/run/secrets/model-platform-key",
  "protocol": "tools-v1",
  "adapter": "deepseek-chat-tools/1",
  "mode": "non-thinking",
  "timeout_ms": 30000
}
```

The existing immutable `kernel.Profile` must also contain `Tools = {protocol: tools-v1, adapter: deepseek-chat-tools/1, mode: non-thinking}`, a nonempty capability revision/approval reference and matching `UsagePolicy = {AdapterRevision: deepseek-chat-tools/1, Mode: final_only}`. An existing immutable snapshot cannot be updated in place. The original installation/publisher factory must create a newly approved publication; this adapter never edits a snapshot, fabricates a proof, or installs a supplier Secret. Missing capability returns `422 tools_protocol_unavailable` before upstream dispatch. The capabilities response exposes `tools_protocol` only for an otherwise callable, approved installation. No new frontend field is required.

Formal Relay profiles also require an explicitly configured `ledger.diagnostics` object (`max_records`, `max_bytes`, `retention_policy_ref`). The example uses64/262144 and an installation-policy placeholder that must be reviewed/replaced. Explicit migrate consumes these values through the original `Core.ConfigureDiagnostics` only when the existing policy row is absent; a conflicting existing policy is rejected rather than reset. Runtime Open and request preparation verify the original row through the same runtime pool and never insert it. This supplies the existing Relay's receipt/termination prerequisite for text and tools, not another ledger. No policy is required for an installation with no formal models; the explicitly controlled offline model remains a separate source producer.

The selected source, exact account/model/revision, explicit mode, adapter, complete billed input/output bounds, price, spend/call caps, TLS/Secret references and production termination/rate/publication producers still need the original EXT-01–06 approvals. `deepseek-chat-tools/1` names this implementation dialect; it is not a claim that a particular account/model is approved. Missing or failed production prerequisites never select the offline profile.

## Request and response flow

`app.Models` → existing `kernelmodel.RelayModel` → existing private mTLS `kernel.Relay` → Higress. There is no provider SDK, supplier URL transport, retry, redirect or fallback. The original signed body digest includes tool definitions, assistant proposals, tool feedback, explicit `thinking.type=disabled`, streaming usage request and the existing output bound. No undocumented `parallel_tool_calls` parameter is sent. The installation's verified input upper bound must cover this entire input, including schemas and observations.

The private `tools-v1` stream has its own bounded normalizer. The public text serializer still rejects tool fields. It preserves choice/index order, freezes each original call ID/name/type, assembles interleaved argument strings, rejects metadata drift/duplicates/sparse indexes/undeclared reasoning and bounds arguments to 64 KiB per call, 16 calls, and visible content to 1 MiB. Existing Relay wire/event limits and parent/request deadlines remain effective. These are adapter ceilings; AR Run and installation limits still apply.

Tool schemas/arguments use the separate `CanonicalToolJSON` domain so the real Calculator's negative minimum and signed bounded operands survive serialization. Duplicate keys, fractional/exponent/unsafe integers remain rejected. Ticket/plan/counter `Canonical` keeps its original nonnegative rule. The public tool Schema hash now covers the actual canonical schema rather than the empty bytes produced by the old wrong-domain helper.

The original Relay records receipt/termination and commits the unique child terminal before emitting DONE. The model adapter then reads authoritative ledger usage. HTTP success, source finish and fixture DONE do not set `TerminalConfirmed` by themselves. DeepSeek cache hit/miss counters map into the existing cached-token field only after consistency checks; missing usage stays unknown, zero stays zero, conflicting final snapshots fail closed. Tool JSON is canonicalized after the child terminal, so invalid/duplicate-key arguments cannot erase already settled model consumption.

The existing Service validates the **entire** batch against frozen Registry schemas, selected versions, trusted permissions and limits before executing the first tool. It continues to use the real `bounded_arithmetic@1` and `list_visible_models@1`, serial execution, original approval bindings, cancellation and unknown-result behavior. Old fixture names `sum_ints` / `echo_text` are not renamed or installed as product tools.

The original Run/Step.Call remains the authority for source call ID, parameters, version and completed result. Model history restores the source ID from that qualified record and checks the assistant proposal and tool feedback against it; it does not trust a duplicate message field. Older stored Parts without the new optional field remain recoverable. Subsequent requests use that ID in assistant `tool_calls` and matching `role=tool/tool_call_id/content` feedback after JSON/MySQL round trips. Missing, forged, repeated or incomplete feedback is rejected. Tool output remains data in a tool message. Each following model turn gets a new original child request ID; the parent Run only projects child usage.

## Evidence scope and reproduction

The original MAAS-9 v0.8 45-vector file is retained byte for byte at `internal/toolwire/testdata/maas9-v08-vectors.json` (SHA256 `e448d03767b4e263a852ca50f862429cd279485601134bb1e92a8eda0e3d38be`). Attachment source: `01a1f1e8-5340-79f2-ac00-5da4fc7c75ca`; original code `ac5e9af`, locks `037be34`. The v0.9 `consumer-map.json` and feedback assertions (`e5033c3`) are consumed as the implementation mapping, rather than treating its old baseline capability rejection as evidence of this bridge.

```powershell
$env:GOMAXPROCS='1'
$env:GOFLAGS='-p=1 -buildvcs=false'
$env:GOMEMLIMIT='256MiB'
go test ./internal/toolwire ./internal/agentruntime/kernelmodel -count=1
```

The HTTP vector test covers first-turn **wire** acceptance/rejection for all 45 captures with actual loopback fragmentation. Fixture-only time labels, authorization, tool execution and full multi-turn oracle expectations are not attributed to that test. Other tests cover source-ID feedback, original Registry/AR batch guards and real MySQL Relay accounting separately. Use the existing owned disposable Unix-socket runner with `MAAS_TEST_PRODUCT_SERVICE=1` and `MAAS_TEST_PRODUCT_PATTERN='^TestProduct|^TestMySQLToolsRelay|^TestARReview'` for the SQL scope.

Production Higress/tools preservation, a real supplier call, target installation/K8s and independent QA are separate acceptance gates. No paid provider call is made by these tests. See this increment's verification report for actual exit codes, failures and limitations.
