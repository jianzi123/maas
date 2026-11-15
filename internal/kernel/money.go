package kernel

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"math/big"
	"regexp"
	"strconv"
	"time"
)

var atomicPattern = regexp.MustCompile(`^(0|[1-9][0-9]{0,37})$`)

func number(s string) (*big.Int, error) {
	if !atomicPattern.MatchString(s) {
		return nil, ErrPrice
	}
	v, _ := new(big.Int).SetString(s, 10)
	return v, nil
}
func add(a, b string) (string, error) {
	x, e := number(a)
	if e != nil {
		return "", e
	}
	y, e := number(b)
	if e != nil {
		return "", e
	}
	x.Add(x, y)
	if len(x.String()) > 38 {
		return "", ErrPrice
	}
	return x.String(), nil
}
func subtract(a, b string) (string, error) {
	x, e := number(a)
	if e != nil {
		return "", e
	}
	y, e := number(b)
	if e != nil {
		return "", e
	}
	x.Sub(x, y)
	if x.Sign() < 0 {
		return "", ErrConflict
	}
	return x.String(), nil
}
func maximum(a, b string) string {
	x, _ := number(a)
	y, _ := number(b)
	if x.Cmp(y) > 0 {
		return a
	}
	return b
}
func hash(v any) string {
	b, _ := json.Marshal(v)
	var value any
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	_ = d.Decode(&value)
	b, _ = json.Marshal(value)
	return fmt.Sprintf("%x", sha256.Sum256(b))
}
func reserved(v *string) string {
	if v == nil {
		return "0"
	}
	return *v
}
func ptr(s string) *string   { return &s }
func decimal(n int64) string { return strconv.FormatInt(n, 10) }

func validatePrice(p *Price) error {
	if p == nil || p.ID == "" || p.Version == "" || p.Scale != 9 || p.Unit != 1000000 || !regexp.MustCompile(`^[A-Z]{3}$`).MatchString(p.Currency) {
		return ErrPrice
	}
	if _, e := time.Parse(time.RFC3339Nano, p.Effective); e != nil {
		return ErrPrice
	}
	for _, v := range []string{p.Input, p.Cached, p.Output, p.Reasoning} {
		if _, e := number(v); e != nil {
			return e
		}
	}
	return nil
}

// Price once after summing all mutually exclusive categories; no float or
// per-chunk rounding is used. Intermediate multiplication uses arbitrary precision.
func priceCost(p *Price, counts [4]int64) (string, error) {
	if e := validatePrice(p); e != nil {
		return "", e
	}
	sum := new(big.Int)
	for i, v := range []string{p.Input, p.Cached, p.Output, p.Reasoning} {
		if counts[i] < 0 || counts[i] > maxCounter {
			return "", ErrPrice
		}
		rate, _ := number(v)
		sum.Add(sum, new(big.Int).Mul(big.NewInt(counts[i]), rate))
	}
	sum.Add(sum, big.NewInt(p.Unit-1))
	sum.Quo(sum, big.NewInt(p.Unit))
	if len(sum.String()) > 38 {
		return "", ErrPrice
	}
	return sum.String(), nil
}
func validatePolicy(p Policy) error {
	if p.Revision == "" || (p.Window != "utc_day" && p.Window != "utc_month") {
		return ErrPolicy
	}
	for _, v := range []*string{p.Limits.Requests, p.Limits.Tokens} {
		if v != nil {
			if _, e := number(*v); e != nil {
				return e
			}
		}
	}
	if p.Limits.Money != nil {
		if !regexp.MustCompile(`^[A-Z]{3}$`).MatchString(p.Limits.Money.Currency) {
			return ErrPrice
		}
		_, e := number(p.Limits.Money.Limit)
		return e
	}
	return nil
}
func window(now time.Time, kind string) (time.Time, time.Time) {
	start := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	if kind == "utc_month" {
		start = time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
		return start, start.AddDate(0, 1, 0)
	}
	return start, start.AddDate(0, 0, 1)
}
func BuildPlan(p Profile, policy Policy, rateRevision string) (Plan, error) {
	out := Plan{Version: "1.0", Alias: p.Alias, SourceID: p.SourceID, ConfigRevision: p.ConfigRevision, CapabilityRevision: p.CapabilityRevision, PolicyRevision: policy.Revision, Window: policy.Window, Metric: "prompt_plus_completion", Requests: "1", RateRevision: rateRevision}
	if e := validatePolicy(policy); e != nil {
		return out, e
	}
	if policy.Limits.Tokens != nil || policy.Limits.Money != nil {
		if !p.BoundVerified || p.InputUpper < 0 || p.OutputUpper < 1 || p.InputUpper > maxCounter-p.OutputUpper {
			return out, ErrBound
		}
		out.Input = ptr(decimal(p.InputUpper))
		out.Output = ptr(decimal(p.OutputUpper))
		out.Total = ptr(decimal(p.InputUpper + p.OutputUpper))
		if policy.Limits.Tokens != nil {
			out.Tokens = out.Total
		}
	}
	if p.Price != nil {
		if e := validatePrice(p.Price); e != nil {
			return out, e
		}
		out.Currency = ptr(p.Price.Currency)
		out.PriceID = ptr(p.Price.ID)
		out.PriceVersion = ptr(p.Price.Version)
		out.PriceHash = ptr(hash(p.Price))
	}
	if policy.Limits.Money != nil {
		if p.Price == nil {
			return out, ErrPrice
		}
		if policy.Limits.Money.Currency != p.Price.Currency {
			return out, ErrPrice
		}
		worst := *p.Price
		worst.Input = maximum(worst.Input, worst.Cached)
		worst.Output = maximum(worst.Output, worst.Reasoning)
		var e error
		var amount string
		amount, e = priceCost(&worst, [4]int64{p.InputUpper, 0, p.OutputUpper, 0})
		out.Money = ptr(amount)
		if e != nil {
			return out, e
		}
	}
	return out, nil
}
