"""Synthetic CPU tests only; no real GPU qualification is manufactured."""
import copy,hashlib,json,sys,tempfile,unittest,subprocess
from pathlib import Path
import numpy as np
from cadence_protocol import digest,write_json
from aa_protocol import make_plan,validate,rows,stratum,check_binding,check_budget,match
from aa_worker import validate_job
from analyze_aa_window import analyze,identity_rows,bank_from_reference,validate_row
class AATests(unittest.TestCase):
 def setUp(self):
  base=Path.cwd()/".cache/aa";base.mkdir(parents=True,exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=base);self.top=Path(self.tmp.name).resolve()
  self.assertTrue(self.top.is_relative_to(base.resolve()))
  self.root=self.top/"window";self.root.mkdir()
  self.plan=make_plan("UNIT_SYNTHETIC_AA","a"*40,False)
  self.lease={"window_id":"UNIT_WINDOW","total_seconds":600,"stop_new_seconds":540,"driver_elapsed_at_send_ns":1000,
    "soft_remaining_ns":539999998000,"hard_remaining_ns":599999998000,"protected_daemon_pid":99999}
  self.jobs={};self.runtime={};self.cells={};self.raw={}
  write_json(self.top/"driver.json",{"plan_sha256":digest(self.plan),"window_id":"UNIT_WINDOW",
     "own_process_collected":True,"within_600s":True,"failure":None})
  for pi,proc in enumerate(("REF","HOLD")):
   folder=self.root/proc;folder.mkdir();(folder/"snapshots").mkdir();(folder/"inputs").mkdir()
   meta={"parameter_full_sha256":"c"*64,"sglang_commit":"UNIT","versions":{"torch":"UNIT"},"GPU":"UNIT_SYNTHETIC",
     "CC":[0,0],"model_config_sha256":"d"*64,"runner_object":99,"forward_function":88,
     "graph_replay_function":77,"execution_stream":7,"graph_identity":{},
     "capture_facts":{v:{"observer_removed":True,"layers":list(range(30)),"capture_sizes":[1,2,4,8],"capturing_calls":120,"source_sha256":("1" if v=="native" else "2")*64,"method":"native" if v=="native" else "mature_kv_binding.mature"} for v in ("native","mature")}}
   for vi,v in enumerate(("native","mature")):
    off=pi*10000+vi*100
    meta["graph_identity"][v]={"graphs":{"4":off+104,"8":off+108},"inputs":{"input_ids":off+1000},
      "scratch":off+2000,"indices":off+3000,"pools":{"4":[off+1,off+2],"8":[off+1,off+2]}}
   self.jobs[proc]={"plan_sha256":digest(self.plan),"process":proc,"window_id":"UNIT_WINDOW","budget":self.lease,
      "budget_lease_sha256":digest(self.lease),"parent_pid":90,"research_lock_fd":7,
      "launch_parent_elapsed_ns":100 if proc=="REF" else 10000000002,
      "soft_parent_deadline_ns":self.lease["soft_remaining_ns"],"hard_parent_deadline_ns":self.lease["hard_remaining_ns"],
      "bank_sha256":None,"bank_path":None}
   if proc=="HOLD":
    bank=bank_from_reference(self.plan,self.root,10000000001,"UNIT_WINDOW")
    write_json(self.root/"bank.json",bank);self.jobs[proc]["bank_sha256"]=digest(bank);self.jobs[proc]["bank_path"]=str(self.root/"bank.json")
   runtime={"plan_sha256":digest(self.plan),"process":proc,"pid":101+pi,"parent_pid":90,
     "evidence_kind":"synthetic_fixture","clock_scope":"UNIT_CLOCK_"+proc,"root_observed_done_ns":1000,
     "job_sha256":digest(self.jobs[proc]),"budget_lease_sha256":digest(self.lease),"metadata":meta}
   self.runtime[proc]=runtime;cells=[];gates=[]
   for scope in ("full","bare_graph"):
    for bs in (3,8):
     refs=[]
     for shape,dtype in (((bs,49152),np.float32),((30,2,bs,3,64),np.float16)):
      x=np.zeros(shape,dtype=dtype);sha=hashlib.sha256(x.tobytes()).hexdigest();name=digest({"shape":shape,"dtype":str(x.dtype),"sha":sha})
      path=folder/"snapshots"/(name+".npz")
      if not path.exists():np.savez_compressed(path,value=x)
      refs.append({"path":path.relative_to(folder).as_posix(),"shape":list(shape),"dtype":str(x.dtype),"raw_sha256":sha})
     for edge in ("before","after"):gates.append({"cell_id":f"R01/{scope}/B{bs}","phase":edge,"all30_layers":True,"status":"passed",
        "snapshots":{v:copy.deepcopy(refs) for v in ("native","mature")}})
     slots=list(range(13*bs));kv=np.zeros((30,2,len(slots),3,64),dtype=np.float16)
     sha=hashlib.sha256(kv.tobytes()).hexdigest();path=folder/"inputs"/(sha+".npz")
     if not path.exists():np.savez_compressed(path,value=kv)
     state={"token_metadata_sha256":"b"*64,"KV_sha256":sha,"read_slots":slots,"KV_shape":list(kv.shape),
            "KV_dtype":"float16","path":path.relative_to(folder).as_posix()}
     bindings={}
     for vi,v in enumerate(("native","mature")):
      actual=meta["graph_identity"][v];cap=4 if bs==3 else 8;graph=actual["graphs"][str(cap)]
      fnid=5000+vi+bs;shared={"callable_object":fnid,"callable_self":99 if scope=="full" else graph,
       "callable_function":88 if scope=="full" else 77,"method":"UNIT","graph_object":graph,"stream":7,
       "inputs":actual["inputs"],"scratch":actual["scratch"],"indices":actual["indices"],"pool":actual["pools"][str(cap)]}
      bindings[v]={"batch":bs,"padded_batch":cap,"implementation":v,"scope":scope,
       "aliases":{k:copy.deepcopy(shared) for k in ("A","Aprime")},"callable_object":fnid,"graph_object":graph,
       "custom_wrapper":False,"eager":False,"capture_caller_verified":True,"registry_identity_checked":True}
     cells.append({"scope":scope,"batch":bs,"clock_scope":runtime["clock_scope"],"ready_ns":1,"input_state":state,"bindings":bindings})
   self.cells[proc]=cells;io=[];records=[];previous=None;done=1000
   for scheduled in [r for r in self.plan["rows"] if r["process"]==proc]:
    c=next(c for c in cells if (c["scope"],c["batch"])==(scheduled["scope"],scheduled["batch"]));ioid=None
    if scheduled["role"]=="boundary_first":
     ioid="IO"+str(len(io));io.append({"id":ioid,"clock_scope":runtime["clock_scope"],"begin_ns":done+2,"end_ns":done+3})
    value=10000000 if proc=="REF" else (9500000 if scheduled["alias"]=="A" else 10500000)
    r=dict(scheduled,status="measured",graph_used=True,clock_scope=runtime["clock_scope"],previous_done_ns=done,previous_id=previous,
      prepare_begin_ns=done+10,ready_ns=done+20,submit_ns=done+30,enqueue_ns=done+1000,
      done_ns=done+20000000,bookkeeping_end_ns=done+20000001,stream_event_ns=value,calls_completed=10,io_id=ioid,
      binding_sha256=digest(c["bindings"][scheduled["implementation"]]),
      input_values_sha256=digest({k:v for k,v in c["input_state"].items() if k!="path"}),
      budget_lease_sha256=digest(self.lease),bank_sha256=self.jobs[proc]["bank_sha256"])
    records.append(r);previous=r["id"];done=r["done_ns"]
   self.raw[proc]=records
   for name,value in (("runtime.json",runtime),("cells.json",cells),("gates.json",gates),("io-events.json",io),
    ("worker-result.json",{"failure":None,"job_sha256":digest(self.jobs[proc])}),
    ("final-invariants.json",{"graphs_unchanged":True,"parameter_sha256":"c"*64})):write_json(folder/name,value)
   write_json(self.root/(proc+"-job.json"),self.jobs[proc])
   self.save_rows(proc)
  self.parent={"pid":90,"plan_sha256":digest(self.plan),"budget":self.lease,"elapsed_ns":21000000000,"failure":None,
    "lifecycle":[{"process":"REF","pid":101,"start_ns":100,"end_ns":10000000000},
                 {"process":"HOLD","pid":102,"start_ns":10000000002,"end_ns":20000000000}]}
  write_json(self.root/"parent.json",self.parent)
 def tearDown(self):self.tmp.cleanup()
 def save_rows(self,proc):
  (self.root/proc/"blocks.jsonl").write_text("".join(json.dumps(r)+"\n" for r in self.raw[proc]))
 def test_schedule_balanced(self):
  validate(self.plan);self.assertEqual(len(self.plan["rows"]),128)
  for key in {stratum(r) for r in self.plan["rows"] if r["qualify"]}:
   group=[r for r in self.plan["rows"] if r["qualify"] and stratum(r)==key]
   self.assertEqual([r["alias"] for r in group].count("A"),2)
   self.assertEqual(len({r["pair"] for r in group}),2)
 def test_endpoint_gate_does_not_establish_zero_bias(self):
  r=analyze(self.plan,self.root);self.assertTrue(r["criteria_satisfied"],r["errors"])
  self.assertFalse(r["engineering_repeatability_qualified"]) # synthetic cannot claim actual GPU
  self.assertFalse(r["zero_alias_bias_established"]);self.assertFalse(r["statistical_equivalence_established"])
  self.assertEqual(r["holdout_matched"],64);self.assertEqual(len(r["alias_pairs"]),32)
  self.assertTrue(all(p["Aprime_minus_A_ns"]==1000000 for p in r["alias_pairs"]))
 def test_alias_callable_change(self):
  b=copy.deepcopy(self.cells["REF"][0]["bindings"]["native"]);b["aliases"]["Aprime"]["callable_object"]+=1
  with self.assertRaisesRegex(ValueError,"alias"):check_binding(b)
 def test_graph_identity_change(self):
  b=copy.deepcopy(self.cells["REF"][0]["bindings"]["native"]);b["graph_object"]+=1
  with self.assertRaisesRegex(ValueError,"graph"):check_binding(b)
 def test_eager_wrapper_rejected(self):
  b=copy.deepcopy(self.cells["REF"][0]["bindings"]["native"]);b["custom_wrapper"]=True
  with self.assertRaises(ValueError):check_binding(b)
 def test_budget_reset(self):
  j=copy.deepcopy(self.jobs["HOLD"]);j["hard_parent_deadline_ns"]=600000000000
  with self.assertRaisesRegex(ValueError,"budget reset"):validate_job(self.plan,j)
 def test_lease_reset(self):
  b=copy.deepcopy(self.lease);b["soft_remaining_ns"]=540000000000
  with self.assertRaisesRegex(ValueError,"budget reset"):check_budget(b)
 def test_duplicate_identity(self):
  self.raw["HOLD"].append(self.raw["HOLD"][0]);self.save_rows("HOLD")
  with self.assertRaisesRegex(ValueError,"duplicate"):identity_rows(self.plan,self.root)
 def test_missing_full_denominator(self):
  self.raw["HOLD"]=self.raw["HOLD"][:-1];self.save_rows("HOLD");r=analyze(self.plan,self.root)
  self.assertFalse(r["criteria_satisfied"]);self.assertEqual((r["planned_rows"],len(r["rows"])),(128,128))
  self.assertEqual(len(r["alias_pairs"]),32)
 def test_clock_mismatch(self):
  self.raw["HOLD"][-1]["clock_scope"]="OTHER";self.save_rows("HOLD")
  self.assertFalse(analyze(self.plan,self.root)["integrity_valid"])
 def test_input_mismatch(self):
  self.raw["HOLD"][-1]["input_values_sha256"]="0"*64;self.save_rows("HOLD")
  self.assertFalse(analyze(self.plan,self.root)["integrity_valid"])
 def test_parameter_mismatch(self):
  self.runtime["HOLD"]["metadata"]["parameter_full_sha256"]="f"*64
  write_json(self.root/"HOLD/runtime.json",self.runtime["HOLD"])
  self.assertFalse(analyze(self.plan,self.root)["integrity_valid"])
 def test_late_bank(self):
  self.parent["lifecycle"][1]["start_ns"]=9999999999
  write_json(self.root/"parent.json",self.parent)
  self.assertFalse(analyze(self.plan,self.root)["integrity_valid"])
 def test_late_worker_launch_rejected(self):
  j=copy.deepcopy(self.jobs["HOLD"]);j["launch_parent_elapsed_ns"]=j["soft_parent_deadline_ns"]
  with self.assertRaisesRegex(ValueError,"late launch"):validate_job(self.plan,j)
 def test_same_caller_cannot_claim_mature(self):
  meta=self.runtime["HOLD"]["metadata"]
  meta["capture_facts"]["mature"]["source_sha256"]=meta["capture_facts"]["native"]["source_sha256"]
  write_json(self.root/"HOLD/runtime.json",self.runtime["HOLD"])
  self.assertFalse(analyze(self.plan,self.root)["integrity_valid"])
 def test_tolerance_boundary(self):
  self.assertTrue(match(9500000,10000000)["matched"]);self.assertFalse(match(9499999,10000000)["matched"])
 def test_disabled_plan_no_execute(self):
  self.assertFalse(self.plan["execution_enabled"])
 def test_128_missing_still_32_pairs(self):
  for proc in ("REF","HOLD"):(self.root/proc/"blocks.jsonl").write_text("")
  r=analyze(self.plan,self.root);self.assertEqual((r["measured_rows"],len(r["alias_pairs"])),(0,32));self.assertFalse(r["criteria_satisfied"])
if __name__=="__main__":unittest.main()
