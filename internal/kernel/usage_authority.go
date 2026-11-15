package kernel

import "reflect"

// UsagePolicy is approved adapter metadata bound into the immutable profile.
// It cannot come from public headers/body or nondecreasing counts alone.
type UsagePolicy struct {
	AdapterRevision string
	Mode            string // final_only or cumulative_until_finish
}
type usageAuthority struct {
	policy                          *UsagePolicy
	latest, final, highest          Usage
	haveLatest, haveFinal, finished bool
}

func (a *usageAuthority) observe(u Usage) error {
	if a.policy == nil {
		return nil
	}
	if a.policy.AdapterRevision == "" {
		return ErrConflict
	}
	if a.haveFinal {
		if !reflect.DeepEqual(a.final, u) {
			return ErrConflict
		}
		return nil
	}
	switch a.policy.Mode {
	case "final_only":
		a.final = u
		a.haveFinal = true
	case "cumulative_until_finish":
		if a.haveLatest && !monotonicUsage(a.highest, u) {
			return ErrConflict
		}
		a.latest = u
		for _, p := range []struct {
			old  **int64
			next *int64
		}{{&a.highest.Input, u.Input}, {&a.highest.Output, u.Output}, {&a.highest.Total, u.Total}, {&a.highest.Cached, u.Cached}, {&a.highest.Reasoning, u.Reasoning}} {
			if p.next != nil {
				v := *p.next
				*p.old = &v
			}
		}
		a.haveLatest = true
		if a.finished {
			a.final = u
			a.haveFinal = true
		}
	default:
		return ErrConflict
	}
	return nil
}
func (a *usageAuthority) finish() {
	a.finished = true
	if a.policy != nil && a.policy.Mode == "cumulative_until_finish" && a.haveLatest && !a.haveFinal {
		a.final = a.latest
		a.haveFinal = true
	}
}
func (a *usageAuthority) result() Usage {
	if a.haveFinal {
		return a.final
	}
	return unavailableUsage("not_provided")
}
func approvedResponseUsage(p *UsagePolicy, u Usage) Usage {
	if p != nil && p.AdapterRevision != "" && (p.Mode == "final_only" || p.Mode == "cumulative_until_finish") {
		return u
	}
	return unavailableUsage("not_provided")
}
