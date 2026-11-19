package kernelmodel

import (
	"context"
	"errors"
	"testing"

	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
)

func TestUnavailableCapabilitiesAndStreamingFrameBoundaries(t *testing.T) {
	m := RelayModel{}
	if e := m.Supports(context.Background(), a.Model{Protocol: "tools-v1"}); !errors.Is(e, a.ErrCapability) {
		t.Fatal(e)
	}
	if e := m.Supports(context.Background(), a.Model{Protocol: "text-v1"}); !errors.Is(e, a.ErrUnavailable) {
		t.Fatal(e)
	}
	text := ""
	w := &relayWriter{emit: func(s string) error { text += s; return nil }}
	for _, b := range []string{"data: {\"choices\":[{\"delta\":{\"content\":\"你", "好\"}}]}\n", "\ndata: [DONE]\n\n"} {
		if _, e := w.Write([]byte(b)); e != nil {
			t.Fatal(e)
		}
	}
	if text != "你好" || !w.done {
		t.Fatal(text, w.done)
	}
	w = &relayWriter{emit: func(string) error { return nil }}
	if _, e := w.Write([]byte("event: error\ndata: {}\n\n")); e == nil {
		t.Fatal("stream error accepted")
	}
}

func TestRemainingBudgetPlanMustBeBoundBeforeRelay(t *testing.T) {
	tokens, money, currency := "10", "20", "TST"
	p := kernel.Plan{Tokens: &tokens, Money: &money, Currency: &currency}
	req := a.Request{TokenUpper: 10, MoneyUpper: 20, Currency: "TST"}
	if e := checkPlan(req, p); e != nil {
		t.Fatal(e)
	}
	req.TokenUpper = 9
	if e := checkPlan(req, p); e == nil {
		t.Fatal("over-reservation")
	}
	req.TokenUpper = 10
	req.Currency = "USD"
	if e := checkPlan(req, p); e == nil {
		t.Fatal("currency mismatch")
	}
	p.Money = nil
	if e := checkPlan(req, p); e == nil {
		t.Fatal("missing bound")
	}
}
