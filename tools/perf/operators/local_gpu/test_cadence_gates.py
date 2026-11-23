"""ELIT-QA-01 vector completeness + historical-producer rejection regressions."""
import copy,hashlib,json
from pathlib import Path
import tempfile,unittest
import numpy as np
from analyze_kv_cadence import validate_gate,load_analysis_plan
from cadence_protocol import make_plan,write_json

class GateTests(unittest.TestCase):
    def setUp(self):
        base=Path.cwd()/".cache"/"strict-gate-tests";base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(base.resolve()))
        (self.root/"snapshots").mkdir()
        self.logits=self.ref(np.zeros((3,49152),dtype=np.float32))
        self.kv=self.ref(np.zeros((30,2,3,3,64),dtype=np.float16))
        self.gate={"cell_id":"R01/full/B3","phase":"before","all30_layers":True,"status":"passed",
                   "snapshots":{"native":[self.logits,self.kv],"mature":[self.logits,self.kv]}}
    def tearDown(self):self.temp.cleanup()
    def ref(self,value,extra=False):
        sha=hashlib.sha256(value.tobytes()).hexdigest()
        name=hashlib.sha256((sha+str(value.shape)+str(value.dtype)+str(extra)).encode()).hexdigest()
        path=self.root/"snapshots"/(name+".npz")
        if extra:np.savez_compressed(path,value=value,wrong=value)
        else:np.savez_compressed(path,value=value)
        return {"path":path.relative_to(self.root).as_posix(),"raw_sha256":sha,"shape":list(value.shape),"dtype":str(value.dtype)}
    def check(self):validate_gate(self.gate,self.root)
    def test_complete_fixture(self):self.check()
    def test_both_empty(self):
        self.gate["snapshots"]={"native":[],"mature":[]}
        with self.assertRaises(ValueError):self.check()
    def test_one_side_empty(self):
        self.gate["snapshots"]["mature"]=[]
        with self.assertRaises(ValueError):self.check()
    def test_variant_missing(self):
        self.gate["snapshots"].pop("native")
        with self.assertRaises(ValueError):self.check()
    def test_asymmetric_extra(self):
        self.gate["snapshots"]["native"].append(self.kv)
        with self.assertRaises(ValueError):self.check()
    def test_single_vector(self):
        self.gate["snapshots"]["native"]=[self.logits]
        with self.assertRaises(ValueError):self.check()
    def test_swapped_roles(self):
        self.gate["snapshots"]["native"]=[self.kv,self.logits]
        with self.assertRaises(ValueError):self.check()
    def test_duplicate_logits_not_KV(self):
        self.gate["snapshots"]["native"]=[self.logits,self.logits]
        with self.assertRaises(ValueError):self.check()
    def test_truncated_logits_even_with_honest_hash(self):
        self.gate["snapshots"]["native"][0]=self.ref(np.zeros((3,128),dtype=np.float32))
        with self.assertRaises(ValueError):self.check()
    def test_both_variants_truncated_still_rejected(self):
        short=self.ref(np.zeros((3,128),dtype=np.float32))
        self.gate["snapshots"]={"native":[short,self.kv],"mature":[short,self.kv]}
        with self.assertRaises(ValueError):self.check()
    def test_both_variants_wrong_bitwidth_still_rejected(self):
        half=self.ref(np.zeros((3,49152),dtype=np.float16))
        self.gate["snapshots"]={"native":[half,self.kv],"mature":[half,self.kv]}
        with self.assertRaises(ValueError):self.check()
    def test_both_variants_missing_layer_still_rejected(self):
        partial=self.ref(np.zeros((29,2,3,3,64),dtype=np.float16))
        self.gate["snapshots"]={"native":[self.logits,partial],"mature":[self.logits,partial]}
        with self.assertRaises(ValueError):self.check()
    def test_wrong_logits_bitwidth(self):
        self.gate["snapshots"]["native"][0]=self.ref(np.zeros((3,49152),dtype=np.float16))
        with self.assertRaises(ValueError):self.check()
    def test_missing_KV_layer(self):
        self.gate["snapshots"]["native"][1]=self.ref(np.zeros((29,2,3,3,64),dtype=np.float16))
        with self.assertRaises(ValueError):self.check()
    def test_nonfinite(self):
        v=np.zeros((3,49152),dtype=np.float32);v[0,0]=np.nan
        self.gate["snapshots"]["native"][0]=self.ref(v)
        with self.assertRaises(ValueError):self.check()
    def test_extra_archive_role(self):
        self.gate["snapshots"]["native"][0]=self.ref(np.zeros((3,49152),dtype=np.float32),True)
        with self.assertRaises(ValueError):self.check()
    def test_wrong_hash(self):
        self.gate["snapshots"]["native"][0]=dict(self.logits,raw_sha256="0"*64)
        with self.assertRaises(ValueError):self.check()
    def test_historical_analyzer_only_compatibility(self):
        plan=make_plan("unit-gate","a"*40)
        legacy=Path(__file__).parent/"legacy_source/analyze_kv_cadence.v0.22.py.txt"
        plan["source_sha256"]["analyze_kv_cadence.py"]=hashlib.sha256(legacy.read_bytes()).hexdigest()
        p=self.root/"plan.json";write_json(p,plan)
        self.assertEqual(load_analysis_plan(p)["schedule"],plan["schedule"])
    def test_unknown_analyzer_digest_rejected(self):
        plan=make_plan("unit-gate","a"*40);plan["source_sha256"]["analyze_kv_cadence.py"]="0"*64
        p=self.root/"plan.json";write_json(p,plan)
        with self.assertRaises(ValueError):load_analysis_plan(p)
    def test_producer_digest_change_rejected(self):
        plan=make_plan("unit-gate","a"*40);plan["source_sha256"]["bench_kv_cadence.py"]="0"*64
        p=self.root/"plan.json";write_json(p,plan)
        with self.assertRaises(ValueError):load_analysis_plan(p)

if __name__=="__main__":unittest.main()
