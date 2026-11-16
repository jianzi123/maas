import copy,unittest
from verify_evidence import verify,SCENARIOS
def example():
    m={k:"synthetic-test-only" for k in ("backend_sha","frontend_sha","deployment_digest","profile_revision","model","source_id","price_revision","environment")}
    m["evidence_kind"]="controlled";m["cases"]={}
    for name in SCENARIOS:
        m["cases"][name]={"status":"PASS","raw_evidence":"synthetic-reference","operation_id":"synthetic-op","cr_uid":"synthetic-uid","publication_id":"synthetic-pub","actual_gateway_route":True,"validation_verified":True,"key_id":"synthetic-key-id","explicit_budget":True,"secret_redacted":True,"request_id":"synthetic-R","fixed_source":True,"upstream_attempts":0 if name in ("quota","revoked") else 1,"business_reservations":0,"request_rows":1,"terminal_rows":1,"summary_count":1,"normal_done":False,"termination_reason":"fixture","normal_done_count":1,"terminal_committed_before_done":True,"lookup_request_id":"synthetic-R","lookup_rows":1,"query_writes":0,"finality_verified":True,"token_actual":19,"matched_price_revision":m["price_revision"],"money_actual":None,"held_preserved":True,"slot_release_changed_finance":False,"replayed_event_same_hash":True}
    m["cases"]["unknown_usage"]["token_actual"]=None
    return m
class Oracle(unittest.TestCase):
    def test_synthetic_valid_shape(self):self.assertEqual(verify(example()),[])
    def test_202_without_route_rejected(self):
        m=example();m["cases"]["publish"]["actual_gateway_route"]=False;self.assertTrue(verify(m))
    def test_unknown_zero_rejected(self):
        m=example();m["cases"]["unknown_usage"]["token_actual"]=0;self.assertTrue(verify(m))
    def test_wrong_lookup_rejected(self):
        m=example();m["cases"]["original_id"]["lookup_request_id"]="other-R";self.assertTrue(verify(m))
    def test_double_terminal_rejected(self):
        m=example();m["cases"]["duplicate_terminal"]["terminal_rows"]=2;self.assertTrue(verify(m))
if __name__=="__main__":unittest.main()
