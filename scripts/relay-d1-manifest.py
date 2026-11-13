"""Describe actual Go source samples, never manufacture missing tool-side identity."""
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
raw=root/'artifacts/go-relay-d1.json'
data=json.loads(raw.read_text())
samples=data['samples']
cases=['content','empty','usage_only','error_then_finish','error_after_content','raw_eof','write_failure','cancel','timeout']
assert len(samples)==len(cases)
allowed={'schema_version','run_id','request_id','instance_id','boot_id','clock_scope','source_revision','publication_id','release_revision','first_protocol_ms','first_content_received_ms','first_content_write_ok_ms','first_content_flush_attempt_ms','end_ms','result','return_error'}
for row in samples:
    assert set(row)==allowed
    for key in ('first_protocol_ms','first_content_received_ms','first_content_write_ok_ms','first_content_flush_attempt_ms'):
        assert row[key] is None or 0<=row[key]<=row['end_ms']
sources=['internal/kernel/relay_forward.go','internal/kernel/relay.go','internal/kernel/public_response.go','internal/kernel/content.go','internal/kernel/relay_sample.go','internal/kernel/relay_sampling_mysql_test.go']
manifest={
 'source_commit_at_manifest':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
 'source_worktree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()),
 'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sources},
 'raw_file':'artifacts/go-relay-d1.json','raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
 'collection_command':'bash scripts/collect-relay-d1.sh',
 'case_to_request':dict(zip(cases,[r['request_id'] for r in samples])),
 'dropped_case':'full_sampler (one additional execution, no exported summary)',
 'component_scope':'Go Relay + temporary MySQL + controlled HTTP upstream; gateway proofs are test adapters',
 'unknown':['client receive','real Higress','Worker','GPU','trace_id','experiment_ref','cell_id','cross-clock calibration'],
 'consumer_commit':'8420aaf956b7d44d52c2bbe52c9d20d15fcdb781',
 'direct_diagnostic_sidecar_import_ready':False,
}
(root/'artifacts/go-relay-d1-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'samples':len(samples),'source_files':len(sources),'raw_sha256':manifest['raw_sha256']}))
