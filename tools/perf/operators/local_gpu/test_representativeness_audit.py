"""Synthetic unit fixtures for disjoint accounting, not new GPU evidence."""
import copy,sys,unittest
from pathlib import Path
from audit_reference_representativeness import decompose,audit,PARTS
class AuditTests(unittest.TestCase):
    def setUp(self):
        self.previous={"id":"UNIT_PREV","done_ns":100,"bookkeeping_end_ns":110,"mode":"query"}
        self.row={"id":"UNIT_ROW","previous_id":"UNIT_PREV","previous_done_ns":100,
          "prepare_begin_ns":140,"ready_ns":160,"submit_ns":200,"enqueue_ns":210,"done_ns":240,
          "bookkeeping_end_ns":250,"role":"boundary_first","mode":"query","clock_scope":"UNIT_CLOCK",
          "status":"measured","calls_completed":10,"phase":"holdout","scope":"full","batch":3,
          "variant":"native","pair":0,"cell":"UNIT_CELL","qualify":True,"query_id":"UNIT_Q",
          "io_id":"UNIT_IO","event_ns":30,"thread_CPU_ns":8}
        self.query={"id":"UNIT_Q","row_id":"UNIT_ROW","begin_ns":165,"end_ns":195,
                    "clock_scope":"UNIT_CLOCK","result":{"returncode":0}}
        self.archive={"id":"UNIT_IO","begin_ns":115,"end_ns":135,"clock_scope":"UNIT_CLOCK",
                      "reason":"pair-boundary","row_ids":["UNIT_PREV"]}
    def calc(self):return decompose(self.row,self.previous,self.query,self.archive,50,"UNIT_CLOCK")
    def test_disjoint_not_double_counted(self):
        r=self.calc();self.assertEqual([r[p+"_ns"] for p in PARTS],[10,20,10,20,5,30,5])
        self.assertEqual(r["gap_ns"],100);self.assertEqual(r["arithmetic_residual_ns"],0)
        self.assertFalse(r["event_is_kernel_sum"])
    def test_prefix_order_overlap_rejected(self):
        self.archive["begin_ns"]=105
        with self.assertRaisesRegex(ValueError,"IO nested"):self.calc()
    def test_previous_clock_coordinate_rejected(self):
        self.row["previous_done_ns"]=99
        with self.assertRaisesRegex(ValueError,"continuous"):self.calc()
    def test_other_clock_rejected(self):
        self.query["clock_scope"]="OTHER"
        with self.assertRaisesRegex(ValueError,"query clock"):self.calc()
    def test_wrong_query_identity_rejected(self):
        self.query["row_id"]="OTHER"
        with self.assertRaisesRegex(ValueError,"query link"):self.calc()
    def test_query_beyond_submit_rejected(self):
        self.query["end_ns"]=201
        with self.assertRaisesRegex(ValueError,"query nested"):self.calc()
    def test_missing_boundary_rejected(self):
        self.archive=None
        with self.assertRaisesRegex(ValueError,"boundary IO"):self.calc()
    def test_missing_measurement_rejected(self):
        self.row["status"]="missing"
        with self.assertRaisesRegex(ValueError,"measured row"):self.calc()
    def test_idle_retains_wait_without_fake_query(self):
        self.row.update(mode="idle",query_id=None);self.query=None
        r=self.calc();self.assertEqual(r["query_ns"],0);self.assertEqual(r["post_query_or_wait_ns"],40)
    def test_root_bookkeeping_explicitly_unobserved(self):
        self.row.update(previous_id=None,previous_done_ns=50,role="cell_transition",io_id=None)
        self.previous=None;self.archive=None
        r=self.calc();self.assertTrue(r["root_bookkeeping_unobserved"])
        self.assertEqual(r["unresolved_prefix_ns"],90)
    def test_all_real_rows_and_signed_failures_preserved(self):
        source=Path(__file__).parent/"evidence/reference-v0.24";report=audit(source)
        self.assertEqual((report["planned_rows"],len(report["rows"]),len(report["strata"])),(128,128,16))
        self.assertEqual((report["unmatched_above"],report["unmatched_below"]),(11,19))
        self.assertFalse(report["original_qualified"]);self.assertFalse(report["GPU_execution"])
        self.assertTrue(report["inputs_unchanged"]);self.assertNotIn("torch",sys.modules)
        self.assertEqual(report["telemetry_coverage"]["holdout_idle"],0)
if __name__=="__main__":unittest.main()
