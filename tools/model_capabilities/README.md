# MAAS-9 offline capability inputs

Three candidate/controlled profiles, source-pinned evidence, synthetic adapter/quality vectors and consumer lock conditions. All profiles are pending approval and execution_enabled=false. Nothing here launches a model, accesses an endpoint/Secret, settles usage or grants production permission.

From repository root:

    python -m unittest discover -s tools/model_capabilities -p "test_*.py" -v
    python tools/model_capabilities/check.py --output <task-output>/capability-report.json
    python tools/model_capabilities/check.py --require-locked

The last command deliberately exits 2 and leaves existing output untouched while inputs are missing. Optional --source-root <captured-source-directory> checks hashes of the reviewed public source cache without network access. The cache is not an engine installation. A source hash match proves file integrity, not compatibility.

Requires existing Python 3.10+ and jsonschema==4.25.0, shared with tools/perf/requirements.txt; no new package installation is performed. check.py validates the tool-owned closed top-level profile schema plus source-kind/parallelism predicates. project_usage is a bounded synthetic oracle, not a production adapter. Outputs contain no text bodies or credentials.

See docs/model-capabilities/README.md for fixed revisions, metadata conflicts, per-role handoff, approval inputs, and protocol/quality entrypoints. Current ticket/terminal/observation versions are 3/3.0/1.0. D1 terminal 3.1 snapshots are proposal-only, rejected by the current reader. Historical v0.1/v0.2 artifacts remain on MAAS-9.
v0.4 KV/page与Prefill/Decode输入、职责自查、运行命令见 docs/model-capabilities/kv-pd-inputs-v0.4.md。比较基线v0.5.6/7ae368e，原v0.5.18仍为部署候选，不混比。
