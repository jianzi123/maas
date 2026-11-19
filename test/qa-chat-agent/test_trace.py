import copy,unittest
from verify_trace import check
def valid():
    # Synthetic oracle fixture; never a claim of running Agent product.
    return {"product_sha":"fixture","contract_version":"qa-normalized-v1","environment":"synthetic","session_id":"S","run_id":"R","owner":"U","evidence_kind":"controlled_model","raw_evidence_verified":True,
    "events":[{"id":"E1","sequence":1,"session_id":"S","run_id":"R"}],
    "tools":[{"call_id":"T","args_hash":"H","executions":1,"authorized":True,"schema_valid":True,"approval_required":True,"approval_id":"P","approval_state":"approved","approved_args_hash":"H","approved_owner":"U","outcome":"known","result_fed_to_model":True,"result_event_id":"E2"}],
    "model_requests":[{"request_id":"M1","attempts":1,"request_rows":1,"terminal_rows":1,"summary_count":1,"through_kernel_gateway":True,"usage_state":"unknown","actual":None,"held_preserved":True}],
    "parent_business_debits":0,"limits":{"step_limit":3,"time_limit_ms":1000,"budget_limit":20,"tool_timeout_ms":200},"event_reconnect_model_calls":0,"event_reconnect_tool_executions":0,"final_answer":True}
class Controls(unittest.TestCase):
    def test_valid_fixture(self):self.assertEqual(check(valid()),[])
    def test_exact_event_duplicate_is_readonly(self):
        v=valid();v["events"]*=2;self.assertEqual(check(v),[])
    def test_changed_event(self):
        v=valid();v["events"].append({**v["events"][0],"sequence":2});self.assertTrue(check(v))
    def test_other_session(self):
        v=valid();v["events"][0]["session_id"]="other";self.assertTrue(check(v))
    def test_denied_tool(self):
        v=valid();v["tools"][0]["authorized"]=False;self.assertTrue(check(v))
    def test_malformed_tool(self):
        v=valid();v["tools"][0]["schema_valid"]=False;self.assertTrue(check(v))
    def test_waiting_approval(self):
        v=valid();v["tools"][0]["approval_state"]="waiting";self.assertTrue(check(v))
    def test_approval_wrong_owner(self):
        v=valid();v["tools"][0]["approved_owner"]="other";self.assertTrue(check(v))
    def test_approval_wrong_args(self):
        v=valid();v["tools"][0]["approved_args_hash"]="changed";self.assertTrue(check(v))
    def test_duplicate_execution(self):
        v=valid();v["tools"][0]["executions"]=2;self.assertTrue(check(v))
    def test_unknown_side_effect_replay(self):
        v=valid();v["tools"][0].update(outcome="unknown",replayed_after_recovery=True);self.assertTrue(check(v))
    def test_reconnect_executes(self):
        v=valid();v["event_reconnect_model_calls"]=1;self.assertTrue(check(v))
    def test_child_double_settle(self):
        v=valid();v["model_requests"][0]["terminal_rows"]=2;self.assertTrue(check(v))
    def test_parent_double_debit(self):
        v=valid();v["parent_business_debits"]=1;self.assertTrue(check(v))
    def test_unknown_as_zero(self):
        v=valid();v["model_requests"][0]["actual"]=0;self.assertTrue(check(v))
    def test_missing_limit(self):
        v=valid();v["limits"].pop("step_limit");self.assertTrue(check(v))
    def test_edit_missing_lineage(self):
        v=valid();v["edit_or_regenerate"]=True;self.assertTrue(check(v))
if __name__=="__main__":unittest.main()
