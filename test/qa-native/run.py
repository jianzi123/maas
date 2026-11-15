"""QA-only observer additions to pinned b5e705d; no framework/kernel patches."""
from pathlib import Path
import argparse,difflib,hashlib,json,os,subprocess,sys,time,signal
p=argparse.ArgumentParser()
p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
a=p.parse_args();a.source=a.source.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
old=(a.source/"run_framework_dummy.py").read_text()
new=old.replace("        def observed_forward(fb, *aa, **kw):","""        qa_snapshots = []
        qa_previous = {}
        report["qa_negative_controls"] = []
        report["qa_releases"] = []
        report["qa_allocations"] = []
        def observed_forward(fb, *aa, **kw):""")
new=new.replace("            logits = result.next_token_logits.detach().clone()", """            logits = result.next_token_logits.detach().clone()
            for tensor, expected_hash in qa_snapshots:
                actual_hash = hashlib.sha256(tensor.cpu().contiguous().view(torch.uint8).numpy().tobytes()).hexdigest()
                if actual_hash != expected_hash:
                    raise AssertionError("retained cloned output changed after later replay")
            snapshot_hash = hashlib.sha256(logits.cpu().contiguous().view(torch.uint8).numpy().tobytes()).hexdigest()
            qa_snapshots.append((logits, snapshot_hash))""")
new=new.replace("            if eager_graph:", """            for label, wrong in [("zero", torch.zeros_like(logits))] + (
                [("stale", qa_previous[raw_bs])] if raw_bs in qa_previous else []):
                try:
                    torch.testing.assert_close(wrong, eager.next_token_logits, rtol=0.02, atol=5e-7)
                    rejected = False
                except AssertionError:
                    rejected = True
                report["qa_negative_controls"].append(dict(
                    scenario=current_label[0], wrong_output=label, rejected=rejected,
                    wrong_reference_max_abs=(wrong.float()-eager.next_token_logits.float()).abs().max().item(),
                    reference_max_abs=eager.next_token_logits.abs().max().item(),
                    rtol=.02, atol=5e-7))
            qa_previous[raw_bs] = logits
            if hashlib.sha256(logits.cpu().contiguous().view(torch.uint8).numpy().tobytes()).hexdigest() != snapshot_hash:
                raise AssertionError("clone mutated during eager reference")
            if eager_graph:""")
new=new.replace('                    "label": current_label[0],', """                    "qa_live_input_ids": g.input_ids[:raw_bs].cpu().tolist(),
                    "qa_live_req_indices": g.req_pool_indices[:raw_bs].cpu().tolist(),
                    "qa_live_cache_locations": g.out_cache_loc[:raw_bs].cpu().tolist(),
                    "clone_preserved_before_reference": True,
                    "label": current_label[0],""")
new=new.replace("            runner.token_to_kv_pool_allocator.free(all_loc)", """            report["qa_releases"].append(dict(req_ids=[ids[i] for i in indices], locations=all_loc.cpu().tolist()))
            runner.token_to_kv_pool_allocator.free(all_loc)""")
new=new.replace("            ids, _, batch = bench.extend(reqs, runner)", """            ids, _, batch = bench.extend(reqs, runner)
            allocated_ids = batch.req_pool_indices.cpu().tolist()
            allocated_lens = batch.seq_lens.cpu().tolist()
            slots = torch.cat([runner.req_to_token_pool.req_to_token[rid,:n] for rid,n in zip(allocated_ids,allocated_lens)])
            assert slots.unique().numel() == slots.numel() and (slots > 0).all()
            report["qa_allocations"].append(dict(batch=bs,req_ids=allocated_ids,locations=slots.cpu().tolist()))""")
# A separate byte comparison verifies the manual probe; it is never installed as default.
new=new.replace('                    manual_prof.export_chrome_trace(', """                    if not torch.equal(kc[loc].contiguous().view(torch.uint8), k.contiguous().view(torch.uint8)):
                        raise AssertionError("manual K bits differ")
                    if not torch.equal(vc[loc].contiguous().view(torch.uint8), v.contiguous().view(torch.uint8)):
                        raise AssertionError("manual V bits differ")
                    manual_prof.export_chrome_trace(""")
assert old!=new
(a.output/"observer.py").write_text(new)
(a.output/"observer.patch").write_text("".join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile="b5e705d/run_framework_dummy.py",tofile="QA/observer.py")))
env=dict(os.environ,HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_DATASETS_OFFLINE="1",PYTHONDONTWRITEBYTECODE="1",PYTHONUNBUFFERED="1")
cache=Path("/var/tmp/maas7-native-555c69ac1872");cache.mkdir(exist_ok=False)
for k,n in (("TRITON_CACHE_DIR","triton"),("CUDA_CACHE_PATH","cuda"),("CUPY_CACHE_DIR","cupy"),("XDG_CACHE_HOME","xdg")):
 (cache/n).mkdir();env[k]=str(cache/n)
before=subprocess.check_output(["/usr/lib/wsl/lib/nvidia-smi","--query-gpu=name,memory.free,clocks.sm,temperature.gpu,power.draw","--format=csv,noheader,nounits"]).decode()
assert float(before.split(",")[1])>=1024
args=[sys.executable,a.output/"observer.py","--source-lock",a.source/"evidence/framework-v0.18/framework-source-lock.json","--output",a.output/"native","--profile"]
start=time.time()
with (a.output/"foreground.log").open("w") as log:
 child=subprocess.Popen([str(x) for x in args],env=env,cwd=a.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 try:rc=child.wait(timeout=600)
 except subprocess.TimeoutExpired:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
  rc=124
after=subprocess.check_output(["/usr/lib/wsl/lib/nvidia-smi","--query-compute-apps=pid,process_name","--format=csv,noheader"]).decode()
record=dict(argv=[str(x) for x in args],pid=child.pid,exit_code=rc,elapsed_s=time.time()-start,before=before,compute_apps_after=after,
 original_sha256=hashlib.sha256(old.encode()).hexdigest(),executed_sha256=hashlib.sha256(new.encode()).hexdigest(),all_children_collected=True)
(a.output/"command.json").write_text(json.dumps(record,indent=2))
print(json.dumps(record),flush=True)
raise SystemExit(rc)
