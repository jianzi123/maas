package kernel

import "testing"

func TestPriceAndReservation(t *testing.T) {
	p := Price{ID: "10000000-0000-4000-8000-000000000001", Version: "test-v1", Source: "source", Model: "model", Currency: "TST", Scale: 9, Unit: 1000000, Effective: "2026-01-01T00:00:00Z", Input: "2000000000", Cached: "200000000", Output: "8000000000", Reasoning: "8000000000"}
	profile := Profile{Alias: "synthetic", SourceID: "source", Price: &p, InputUpper: 100, OutputUpper: 40, BoundVerified: true}
	policy := Policy{Window: "utc_day", Revision: "policy-v1", Limits: Limits{Requests: ptr("100"), Tokens: ptr("1000"), Money: &MoneyLimit{Currency: "TST", Limit: "999999999"}}}
	plan, e := BuildPlan(profile, policy, "rate-v1")
	if e != nil || reserved(plan.Tokens) != "140" || reserved(plan.Money) != "520000" {
		t.Fatalf("plan=%+v err=%v", plan, e)
	}
	cost, e := priceCost(&p, [4]int64{8, 4, 4, 3})
	if e != nil || cost != "72800" {
		t.Fatalf("cost=%s err=%v", cost, e)
	}
	p.Input = "1"
	p.Cached = "1"
	p.Output = "1"
	p.Reasoning = "1"
	cost, e = priceCost(&p, [4]int64{1, 1, 1, 1})
	if e != nil || cost != "1" {
		t.Fatalf("round once cost=%s err=%v", cost, e)
	}
	p.Input = "99999999999999999999999999999999999999"
	if _, e = priceCost(&p, [4]int64{maxCounter, 0, 0, 0}); e == nil {
		t.Fatal("overflow must reject")
	}
	profile.BoundVerified = false
	if _, e = BuildPlan(profile, policy, "rate-v1"); e != ErrBound {
		t.Fatal("unverified bound", e)
	}
}
func TestUsageIndependentDimensions(t *testing.T) {
	in, out, total := int64(12), int64(7), int64(19)
	p := Price{ID: "test", Version: "v1", Currency: "TST", Scale: 9, Unit: 1000000, Effective: "2026-01-01T00:00:00Z", Input: "2", Cached: "1", Output: "4", Reasoning: "4"}
	tok, cost, basis, e := actualUsage(Usage{Input: &in, Output: &out}, &p)
	if e != nil || tok == nil || *tok != "19" || cost != nil || basis != "component_sum" {
		t.Fatal(tok, cost, basis, e)
	}
	total = 20
	if _, _, _, e = actualUsage(Usage{Input: &in, Output: &out, Total: &total}, &p); e == nil {
		t.Fatal("contradictory usage")
	}
	s, e := settle("140", nil, false)
	if e != nil || s.Held != "140" || s.Known != "0" {
		t.Fatal(s, e)
	}
	s, e = settle("140", ptr("19"), false)
	if e != nil || s.Released != "121" || s.Known != "19" {
		t.Fatal(s, e)
	}
}
