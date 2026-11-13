package kernel

import "testing"

func TestUsageAuthority(t *testing.T) {
	value := func(n int64) *int64 { return &n }
	base := Usage{Input: value(12), Output: value(7), Total: value(19), Cached: value(4), Reasoning: value(3), Source: "upstream"}
	for _, field := range []string{"output", "cached", "missing"} {
		t.Run("conflicting_final_"+field, func(t *testing.T) {
			a := usageAuthority{policy: &UsagePolicy{"test-v1", "final_only"}}
			if a.observe(base) != nil || a.observe(base) != nil {
				t.Fatal("identical final must be idempotent")
			}
			next := base
			if field == "output" {
				next.Output = value(8)
				next.Total = value(20)
			} else if field == "cached" {
				next.Cached = value(5)
			} else {
				next.Total = nil
			}
			if a.observe(next) == nil {
				t.Fatal("conflicting final accepted")
			}
		})
	}
	t.Run("progress_does_not_become_actual_before_boundary", func(t *testing.T) {
		a := usageAuthority{policy: &UsagePolicy{"test-v1", "cumulative_until_finish"}}
		first := base
		first.Output = value(5)
		first.Total = value(17)
		if a.observe(first) != nil || a.observe(base) != nil || a.result().Input != nil {
			t.Fatal("progress promoted or summed")
		}
		a.finish()
		if *a.result().Total != 19 {
			t.Fatal("final cumulative snapshot lost")
		}
		next := base
		next.Cached = value(5)
		if a.observe(next) == nil {
			t.Fatal("post-final mutation accepted")
		}
	})
	t.Run("missing_policy_is_diagnostic_only", func(t *testing.T) {
		a := usageAuthority{}
		a.observe(base)
		a.finish()
		if a.result().Input != nil || approvedResponseUsage(nil, base).Input != nil {
			t.Fatal("unapproved usage became actual")
		}
	})
	t.Run("missing_progress_field_does_not_erase_high_water", func(t *testing.T) {
		a := usageAuthority{policy: &UsagePolicy{"test-v1", "cumulative_until_finish"}}
		a.observe(base)
		partial := base
		partial.Total = nil
		partial.Output = nil
		a.observe(partial)
		next := base
		next.Output = value(6)
		next.Total = value(18)
		if a.observe(next) == nil {
			t.Fatal("missing progress hid a decreasing counter")
		}
	})
}
