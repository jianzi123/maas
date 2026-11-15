package kernel

import (
	"github.com/google/uuid"
	"sync/atomic"
	"time"
)

// RelaySample is an INTERNAL diagnostic source record, not Observation1.0 or
// accounting evidence. All optional instants use one process-monotonic scope.
type RelaySample struct {
	Schema          string   `json:"schema_version"`
	RunID           string   `json:"run_id"`
	RequestID       string   `json:"request_id"`
	InstanceID      string   `json:"instance_id"`
	BootID          string   `json:"boot_id"`
	ClockScope      string   `json:"clock_scope"`
	SourceRevision  string   `json:"source_revision"`
	PublicationID   string   `json:"publication_id"`
	ReleaseRevision string   `json:"release_revision"`
	ProtocolMS      *float64 `json:"first_protocol_ms"`
	ContentMS       *float64 `json:"first_content_received_ms"`
	WriteMS         *float64 `json:"first_content_write_ok_ms"`
	FlushMS         *float64 `json:"first_content_flush_attempt_ms"`
	EndMS           float64  `json:"end_ms"`
	Result          string   `json:"result"`
	ReturnError     bool     `json:"return_error"`
}

// Construct once at process boot. Sampling is optional, bounded, nonblocking;
// consumers drain outside the request. No callback, file IO or new DB write.
type RelaySampler struct {
	run, instance, boot, revision string
	records                       chan RelaySample
	dropped                       atomic.Uint64
}

func NewRelaySampler(run, instance, revision string, capacity int) *RelaySampler {
	if run == "" || len(run) > 128 || !validUUID(instance) || revision == "" || len(revision) > 128 || capacity < 1 || capacity > 4096 {
		return nil
	}
	return &RelaySampler{run: run, instance: instance, boot: uuid.NewString(), revision: revision, records: make(chan RelaySample, capacity)}
}
func (s *RelaySampler) Records() <-chan RelaySample { return s.records }
func (s *RelaySampler) Dropped() uint64             { return s.dropped.Load() }
func (s *RelaySampler) offer(v RelaySample) {
	select {
	case s.records <- v:
	default:
		s.dropped.Add(1)
	}
}
func elapsedMS(start, at time.Time) *float64 {
	v := float64(at.Sub(start)) / float64(time.Millisecond)
	return &v
}
