package kernel

import (
	"github.com/google/uuid"
	"testing"
)

func TestSamplerBoundedDrop(t *testing.T) {
	s := NewRelaySampler("run", uuid.NewString(), "test-only", 1)
	for i := 0; i < 10000; i++ {
		s.offer(RelaySample{})
	}
	if s.Dropped() != 9999 {
		t.Fatal(s.Dropped())
	}
	if len(s.records) != 1 {
		t.Fatal("unbounded queue")
	}
}
func BenchmarkRelaySamplerFull(b *testing.B) {
	s := NewRelaySampler("run", uuid.NewString(), "test-only", 1)
	s.offer(RelaySample{})
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		s.offer(RelaySample{})
	}
}
