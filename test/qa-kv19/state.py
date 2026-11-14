"""Independent GPU state collection: all layers/new slots and non-target bit guards."""
import argparse,sys,os,json,hashlib,contextlib
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_DATASETS_OFFLINE="1")
p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--variant",choices=("native","mature"),required=True);a=p.parse_args()
sys.path.insert(0,str(a.source))
import torch,numpy as np
import run_framework_dummy as baseline
from native_kv_binding import mature_kv_binding
from sglang.srt.model_executor.model_runner import ModelRunner
original=ModelRunner.forward;states={};logits={};rows=[];params=[]
def observed(self,fb,*aa,**kw):
 isdecode=fb.forward_mode.is_decode();loc=fb.out_cache_loc[:fb.batch_size] if isdecode else None
 pool=self.token_to_kv_pool;layers=range(self.start_layer,self.end_layer)
 if isdecode:
  mask=torch.ones(pool.get_key_buffer(self.start_layer).shape[0],dtype=torch.bool,device="cuda")
  mask[0]=False;mask[loc]=False
  before=[(pool.get_key_buffer(i)[mask].clone(),pool.get_value_buffer(i)[mask].clone()) for i in layers]
 value,graph=original(self,fb,*aa,**kw)
 if graph:
  if not params:
   h=hashlib.sha256()
   for parameter in self.model.parameters():h.update(parameter.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
   params.append(h.hexdigest())
  index=len(rows);assert len(list(layers))==30 and (loc>0).all() and loc.unique().numel()==loc.numel()
  for i,(k,v) in zip(layers,before):
   assert torch.equal(k.contiguous().view(torch.uint8),pool.get_key_buffer(i)[mask].contiguous().view(torch.uint8))
   assert torch.equal(v.contiguous().view(torch.uint8),pool.get_value_buffer(i)[mask].contiguous().view(torch.uint8))
  k=torch.stack([pool.get_key_buffer(i).index_select(0,loc) for i in layers]);v=torch.stack([pool.get_value_buffer(i).index_select(0,loc) for i in layers])
  states["k%02d"%index]=k.detach().cpu().numpy();states["v%02d"%index]=v.detach().cpu().numpy()
  logits["decode%02d"%index]=value.next_token_logits.detach().clone().cpu().numpy()
  rows.append(dict(step=index,batch=fb.batch_size,locations=loc.cpu().tolist(),non_target_real_slots_bitwise_unchanged=True,layers=30))
 return value,graph
try:
 with contextlib.ExitStack() as stack:
  if a.variant=="mature":stack.enter_context(mature_kv_binding())
  ModelRunner.forward=observed;sys.argv=[sys.argv[0],"--output",str(a.output),"--source-lock",str(a.source/"evidence/framework-v0.18/framework-source-lock.json")]
  rc=baseline.main()
finally:ModelRunner.forward=original
assert rc==0 and len(rows)==12
np.savez_compressed(a.output/"kv-states.npz",**states);np.savez_compressed(a.output/"independent-logits.npz",**logits)
(a.output/"qa-state.json").write_text(json.dumps(dict(variant=a.variant,rows=rows,parameter_sha256=params[0],scope="all30 layers actual new locations; non-target real slots checked; dummy0 excluded"),indent=2))
