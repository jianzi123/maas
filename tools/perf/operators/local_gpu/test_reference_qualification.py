"""Synthetic unit fixtures only; these are not GPU experiment evidence."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
import numpy as np
from cadence_protocol import digest
from reference_protocol import make_plan, validate, stratum, match
from analyze_cadence_reference import evaluate


class QualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        (cls.root/'snapshots').mkdir();cls.refs={}
        for b in (3,8):
            refs=[]
            for shape,dtype in (((b,49152),np.float32),((30,2,b,3,64),np.float16)):
                value=np.zeros(shape,dtype=dtype);sha=hashlib.sha256(value.tobytes()).hexdigest()
                name=digest({'sha':sha,'shape':list(shape),'dtype':str(value.dtype)})
                path=cls.root/'snapshots'/(name+'.npz');np.savez_compressed(path,value=value)
                refs.append({'path':path.relative_to(cls.root).as_posix(),'raw_sha256':sha,'shape':list(shape),'dtype':str(value.dtype)})
            cls.refs[b]=refs
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.plan=make_plan('UNIT_SYNTHETIC','a'*40);clock='unit-process-clock'
        self.runtime={'plan_sha256':digest(self.plan),'clock_scope':clock,'root_observed_done_ns':1000000000,
                      'frozen_ns':1000000001,'root_kind':'only_initial_boot_event_observation'}
        self.rows=[];self.queries=[];self.ios=[];self.gates=[];prev=1000000000;prev_id=None;self.bank=None
        for s in self.plan['rows']:
            if s['phase']=='holdout' and self.bank is None:
                refs=[r for r in self.rows if r['phase']=='reference']
                targets={stratum(r):10000000 for r in refs if r['role']!='cell_transition'}
                self.bank={'schema':'reference-bank1','clock_scope':clock,'plan_sha256':digest(self.plan),
                   'targets_ns':targets,'reference_row_ids':[r['id'] for r in refs if r['role']!='cell_transition'],
                   'reference_rows_sha256':digest(refs),'frozen_ns':prev+20,'match_abs_ns':250000,
                   'match_relative':.05,'same_target_for_query_and_idle':True}
            qid=ioid=None
            if s['role']=='boundary_first':
                ioid='io'+str(len(self.ios));self.ios.append({'id':ioid,'reason':'pair-boundary','begin_ns':prev+10,
                    'end_ns':prev+30,'clock_scope':clock,'row_ids':[prev_id]})
            if s['mode']=='query':
                qid=s['id']+'/query';self.queries.append({'id':qid,'row_id':s['id'],'begin_ns':prev+200,
                    'end_ns':prev+9000000,'clock_scope':clock,'result':{'returncode':0,'csv':'UNIT'}})
            r=dict(s,status='measured',clock_scope=clock,previous_id=prev_id,previous_done_ns=prev,
                prepare_begin_ns=prev+100,ready_ns=prev+150,submit_ns=prev+10000000,enqueue_ns=prev+10500000,
                done_ns=prev+11000000,bookkeeping_end_ns=prev+11000005,calls_completed=10,event_ns=1000000,
                query_id=qid,io_id=ioid,sleep_begin_ns=prev+200 if s['mode']=='idle' else None,
                sleep_end_ns=prev+9999999 if s['mode']=='idle' else None,
                sleep_requested_ns=9999800 if s['mode']=='idle' else 0,bank_sha256=digest(self.bank) if self.bank else None)
            self.rows.append(r);prev=r['done_ns'];prev_id=r['id']
        for phase in ('reference','holdout'):
            for scope in ('full','bare_graph'):
                for b in (3,8):
                    for edge in ('before','after'):
                        self.gates.append({'cell_id':f'R01/{scope}/B{b}','phase':f'{phase}-{edge}',
                             'all30_layers':True,'status':'passed','snapshots':{v:copy.deepcopy(self.refs[b]) for v in ('native','mature')}})
        cells=[]
        for phase in ('reference','holdout'):
            for scope in ('full','bare_graph'):
                for b in (3,8):
                    cell_rows=[r for r in self.rows if (r['phase'],r['scope'],r['batch'])==(phase,scope,b)]
                    for r in cell_rows:r['input_sha256']='b'*64
                    cells.append({'phase':phase,'scope':scope,'batch':b,'clock_scope':clock,'input_sha256':'b'*64,
                                  'begin_ns':cell_rows[0]['previous_done_ns'],'ready_ns':cell_rows[0]['previous_done_ns']+50})
        # Reference row hash includes all real row fields.
        self.bank['reference_rows_sha256']=digest([r for r in self.rows if r['phase']=='reference'])
        for r in self.rows:
            if r['phase']=='holdout':r['bank_sha256']=digest(self.bank)
        (self.root/'cells.json').write_text(json.dumps(cells))
        (self.root/'final-invariants.json').write_text(json.dumps({'parameters_unchanged':True,'graphs_unchanged':True,
             'resources':{'free':2**30,'reserved':1,'total':2**33}}))
    def report(self):return evaluate(self.plan,self.rows,self.bank,self.runtime,self.queries,self.ios,self.gates,self.root)
    def test_balanced_frozen_schedule(self):
        validate(self.plan);r=self.report();self.assertTrue(r['qualified'],r['errors'])
        self.assertEqual(r['completed_calls'],1280)
        for key in r['strata']:
            rows=[x for x in self.rows if x['qualify'] and stratum(x)==key]
            self.assertEqual([x['mode'] for x in rows].count('query'),2)
            self.assertEqual([x['mode'] for x in rows].count('idle'),2)
    def test_previous_done_not_reset(self):
        self.rows[56]['previous_done_ns']+=1
        self.assertFalse(self.report()['integrity_valid'])
    def test_other_clock_rejected(self):
        self.rows[70]['clock_scope']='other';self.assertFalse(self.report()['qualified'])
    def test_policy_postfit_rejected(self):
        k=next(iter(self.bank['targets_ns']));self.bank['targets_ns'][k]+=1
        self.assertFalse(self.report()['integrity_valid'])
    def test_late_freeze_rejected(self):
        self.bank['frozen_ns']=self.rows[-1]['submit_ns'];self.assertFalse(self.report()['qualified'])
    def test_missing_and_slow_not_dropped(self):
        for r in self.rows[70:]:r.update(status='missing',calls_completed=0)
        report=self.report();self.assertFalse(report['qualified']);self.assertEqual(len(report['details']),128)
        self.assertEqual(report['holdout_planned'],64)
    def test_unmatched_is_valid_negative_result(self):
        # Changing the common prior isn't allowed; a real large gap remains visible.
        r=self.rows[-1];r['submit_ns']+=2000000;r['enqueue_ns']+=2000000;r['done_ns']+=2000000;r['bookkeeping_end_ns']+=2000000
        report=self.report();self.assertTrue(report['integrity_valid'],report['errors'])
        self.assertFalse(report['qualified']);self.assertEqual(report['matched_holdout'],63)
    def test_query_orphan_rejected(self):
        self.queries.append(dict(self.queries[0],id='orphan'));self.assertFalse(self.report()['integrity_valid'])
    def test_query_identity_rejected(self):
        self.rows[-1]['query_id']='not-linked';self.assertFalse(self.report()['integrity_valid'])
    def test_boundary_io_required(self):
        next(r for r in self.rows if r['role']=='boundary_first')['io_id']=None
        self.assertFalse(self.report()['qualified'])
    def test_empty_one_sided_asymmetric_missing_roles_rejected(self):
        for snapshots in ({'native':[],'mature':[]},{'native':self.refs[3],'mature':[]},
                          {'native':self.refs[3][:1],'mature':self.refs[3]}, {'native':self.refs[3]}):
            with self.subTest(snapshots=snapshots):
                original=self.gates[0]['snapshots'];self.gates[0]['snapshots']=snapshots
                self.assertFalse(self.report()['integrity_valid']);self.gates[0]['snapshots']=original
    def test_complete_vector_shape_required(self):
        self.gates[0]['snapshots']['native'][0]['shape']=[3,1];self.assertFalse(self.report()['qualified'])
    def test_missing_gate_rejected(self):
        self.gates.pop();self.assertFalse(self.report()['qualified'])
    def test_missing_runtime_and_bank_no_success(self):
        self.runtime=None;self.bank=None;self.assertFalse(self.report()['qualified'])
    def test_plan_tolerance_mutation(self):
        self.plan['config']['match_relative']=.5
        with self.assertRaises(ValueError):validate(self.plan)
    def test_input_identity_rejected(self):
        self.rows[-1]['input_sha256']='c'*64
        self.assertFalse(self.report()['qualified'])
    def test_final_invariants_required(self):
        (self.root/'final-invariants.json').write_text('{}')
        self.assertFalse(self.report()['qualified'])
    def test_tolerance_boundary(self):
        self.assertTrue(match(10500000,10000000)['matched']);self.assertFalse(match(10500001,10000000)['matched'])

if __name__=='__main__':unittest.main()
