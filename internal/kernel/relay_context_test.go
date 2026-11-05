package kernel

import (
	"context"
	"testing"
	"time"
)

func TestRelayFirstContextReason(t *testing.T) {
	parent, cancel := context.WithCancel(context.Background())
	child, stop := context.WithDeadline(parent, time.Now().Add(-time.Second))
	defer stop()
	cancel()
	result, _ := relayFailure(parent, child, nil, "interrupted")
	if result != "timed_out" {
		t.Fatal("later parent cancel overwrote deadline", result)
	}
	parent2, cancel2 := context.WithCancel(context.Background())
	child2, stop2 := context.WithTimeout(parent2, time.Hour)
	defer stop2()
	cancel2()
	result, _ = relayFailure(parent2, child2, nil, "interrupted")
	if result != "cancelled" {
		t.Fatal(result)
	}
}
