"""Targeted native pool reuse after free, without clear or model forward."""
import argparse,hashlib,json,os,subprocess,sys,time,signal
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
a.source=a.source.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
old=(a.source/"run_framework_dummy.py").read_text()
addition="""        qa_before = dict(req_free=runner.req_to_token_pool.available_size(),kv_free=runner.token_to_kv_pool_allocator.available_size())
        req1 = runner.req_to_token_pool.alloc(8)
        kv1 = runner.token_to_kv_pool_allocator.alloc(512)
        assert len(set(req1)) == 8 and kv1.unique().numel() == 512 and (kv1 > 0).all()
        runner.req_to_token_pool.free(req1)
        runner.token_to_kv_pool_allocator.free(kv1)
        req2 = runner.req_to_token_pool.alloc(8)
        kv2 = runner.token_to_kv_pool_allocator.alloc(512)
        assert set(req1) == set(req2) and set(kv1.cpu().tolist()) == set(kv2.cpu().tolist())
        runner.req_to_token_pool.free(req2)
        runner.token_to_kv_pool_allocator.free(kv2)
        qa_after = dict(req_free=runner.req_to_token_pool.available_size(),kv_free=runner.token_to_kv_pool_allocator.available_size())
        assert qa_before == qa_after == dict(req_free=8,kv_free=512)
        report.update(status="QA_pool_reuse_passed",qa_no_clear_used=True,qa_before=qa_before,qa_after=qa_after,
                      qa_reused_req_ids=sorted(req2),qa_reused_KV_slots=sorted(kv2.cpu().tolist()))
        return 0
"""
new=old.replace("        stable = {",addition+"        stable = {")
(a.output/"pool_observer.py").write_text(new)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",TRITON_CACHE_DIR="/var/tmp/maas7-native-555c69ac1872/triton",CUDA_CACHE_PATH="/var/tmp/maas7-native-555c69ac1872/cuda",XDG_CACHE_HOME="/var/tmp/maas7-native-555c69ac1872/xdg")
args=[sys.executable,a.output/"pool_observer.py","--source-lock",a.source/"evidence/framework-v0.18/framework-source-lock.json","--output",a.output/"result"]
start=time.time()
with (a.output/"foreground.log").open("w") as f:
 child=subprocess.Popen([str(x) for x in args],cwd=a.source,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 try:rc=child.wait(timeout=600)
 except subprocess.TimeoutExpired:
  os.killpg(child.pid,signal.SIGKILL);child.wait();rc=124
record=dict(argv=[str(x) for x in args],pid=child.pid,exit_code=rc,elapsed_s=time.time()-start,executed_sha256=hashlib.sha256(new.encode()).hexdigest())
(a.output/"command.json").write_text(json.dumps(record,indent=2));print(json.dumps(record))
raise SystemExit(rc)
