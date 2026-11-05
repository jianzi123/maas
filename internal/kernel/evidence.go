package kernel

import (
	"context"
	"database/sql"
	"errors"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"time"
)

// WitnessVerifier is the installation-approved H1/H3 producer verification port.
// It must verify issuer/instance identity, approved mechanism, signature, effective
// config and exact credential generation BEFORE returning this binding. No
// production verifier or HTTP producer is installed by the default binary.
type Witness struct {
	ID, PublicationID, Issuer, Kind, ProfileHash string
	Observed, Expires                            time.Time
}
type WitnessVerifier interface {
	Verify(context.Context, []byte) (Witness, error)
}

func (s *Store) CaptureWitness(ctx context.Context, v WitnessVerifier, payload []byte) error {
	if v == nil || len(payload) == 0 || len(payload) > 8192 {
		return ErrUnavailable
	}
	w, e := v.Verify(ctx, payload)
	if e != nil {
		return ErrUnavailable
	}
	if !validUUID(w.ID) || !validUUID(w.PublicationID) || w.Issuer == "" || (w.Kind != "runtime" && w.Kind != "gateway") {
		return ErrPolicy
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		p, e := s.profile(ctx, tx, w.PublicationID)
		if e != nil {
			return e
		}
		if hash(p) != w.ProfileHash {
			return ErrConflict
		}
		t, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if w.Observed.After(t) || !w.Observed.Before(w.Expires) || !t.Before(w.Expires) {
			return ErrConflict
		}
		var old string
		e = tx.QueryRowContext(ctx, "SELECT payload_sha256 FROM publication_proofs WHERE proof_id=?", w.ID).Scan(&old)
		if e == nil {
			if old == protocol.Digest(payload) {
				return nil
			}
			return ErrConflict
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		_, e = tx.ExecContext(ctx, "INSERT INTO publication_proofs(proof_id,publication_id,kind,issuer,payload_sha256,profile_sha256,observed_at,expires_at) VALUES(?,?,?,?,?,?,?,?)", w.ID, w.PublicationID, w.Kind, w.Issuer, protocol.Digest(payload), w.ProfileHash, w.Observed, w.Expires)
		return e
	})
}
func (s *Store) RevokeWitness(ctx context.Context, id string) error {
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		_, e := tx.ExecContext(ctx, "UPDATE publication_proofs SET revoked=TRUE WHERE proof_id=?", id)
		return e
	})
}

// DurableProofs reads persisted, verified facts in the caller's transaction.
// H2 closure is deliberately unavailable until a real approved reporter exists.
type DurableProofs struct{ Cluster string }

func (d DurableProofs) Closure(context.Context, *sql.Tx, Snapshot, string) (Closure, error) {
	return Closure{}, ErrUnavailable
}
func (d DurableProofs) Publication(ctx context.Context, tx *sql.Tx, p mysqlstore.Publication) (mysqlstore.Evidence, error) {
	out := mysqlstore.Evidence{CRUID: p.CRUID, Binding: p.Binding, AccountingReady: true, Refs: []string{}}
	t, e := now(ctx, tx)
	if e != nil {
		return out, e
	}
	var profile []byte
	var digest string
	var blocked bool
	e = tx.QueryRowContext(ctx, "SELECT snapshot_json,snapshot_sha256,blocked FROM invocation_profiles WHERE publication_id=?", p.PublicationID).Scan(&profile, &digest, &blocked)
	if e != nil || blocked {
		return out, release.ErrDependencyMissing
	}
	// Validate namespace/cluster through the same publication row, not a proof UUID.
	var uid string
	e = tx.QueryRowContext(ctx, "SELECT cr_uid FROM publications WHERE cluster_id=? AND publication_id=?", d.Cluster, p.PublicationID).Scan(&uid)
	if e != nil || uid != p.CRUID {
		return out, release.ErrDependencyMissing
	}
	out.FreshUntil = t.Add(365 * 24 * time.Hour)
	for _, kind := range []string{"runtime", "gateway"} {
		var id string
		var expires time.Time
		e = tx.QueryRowContext(ctx, "SELECT proof_id,expires_at FROM publication_proofs WHERE publication_id=? AND profile_sha256=? AND kind=? AND revoked=FALSE AND observed_at<=? AND expires_at>? ORDER BY expires_at DESC,proof_id LIMIT 1", p.PublicationID, digest, kind, t, t).Scan(&id, &expires)
		if errors.Is(e, sql.ErrNoRows) {
			continue
		}
		if e != nil {
			return out, e
		}
		out.Refs = append(out.Refs, id)
		if expires.Before(out.FreshUntil) {
			out.FreshUntil = expires
		}
		if kind == "runtime" {
			out.RuntimeReady = true
		} else {
			out.GatewayApplied = true
		}
	}
	var validationID string
	e = tx.QueryRowContext(ctx, `SELECT v.intent_id FROM validation_intents v JOIN validation_receipts r ON r.intent_id=v.intent_id AND r.request_id=v.request_id AND r.publication_id=v.publication_id AND r.profile_sha256=v.profile_sha256 WHERE v.publication_id=? AND v.profile_sha256=? AND v.revoked=FALSE AND v.expires_at>? LIMIT 1`, p.PublicationID, digest, t).Scan(&validationID)
	if e == nil {
		out.ValidationPassed = true
		out.Refs = append(out.Refs, validationID)
	} else if !errors.Is(e, sql.ErrNoRows) {
		return out, e
	}
	return out, nil
}

type ValidationIntent struct {
	ID, RequestID, PublicationID, KeyID, PolicyRevision, ProfileHash string
	Expires                                                          time.Time
}

func (s *Store) PlanValidation(ctx context.Context, p Profile, key, policy string, expires time.Time) (ValidationIntent, error) {
	out := ValidationIntent{}
	if policy == "" || !validUUID(key) {
		return out, ErrPolicy
	}
	e := s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		stored, e := s.profile(ctx, tx, p.Binding.PublicationID)
		if e != nil {
			return e
		}
		if hash(stored) != hash(p) {
			return ErrConflict
		}
		var purpose string
		if e = tx.QueryRowContext(ctx, "SELECT purpose FROM key_metadata WHERE key_id=?", key).Scan(&purpose); e != nil || purpose != "validation" {
			return ErrKey
		}
		t, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if !t.Before(expires) {
			return ErrPolicy
		}
		e = tx.QueryRowContext(ctx, "SELECT intent_id,request_id,publication_id,key_id,policy_revision,profile_sha256,expires_at FROM validation_intents WHERE publication_id=? AND policy_revision=?", p.Binding.PublicationID, policy).Scan(&out.ID, &out.RequestID, &out.PublicationID, &out.KeyID, &out.PolicyRevision, &out.ProfileHash, &out.Expires)
		if e == nil {
			if out.KeyID != key || out.ProfileHash != hash(p) {
				return ErrConflict
			}
			return nil
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		out = ValidationIntent{uuid.NewString(), uuid.NewString(), p.Binding.PublicationID, key, policy, hash(p), expires}
		_, e = tx.ExecContext(ctx, "INSERT INTO validation_intents(intent_id,publication_id,policy_revision,request_id,key_id,profile_sha256,expires_at) VALUES(?,?,?,?,?,?,?)", out.ID, out.PublicationID, policy, out.RequestID, key, out.ProfileHash, expires)
		return e
	})
	return out, e
}
func (s *Store) gate(ctx context.Context, tx *sql.Tx, g ActiveGate, in Input) (release.Binding, error) {
	purpose := in.Purpose
	if purpose == "" {
		purpose = "serving"
	}
	var keyPurpose string
	e := tx.QueryRowContext(ctx, "SELECT purpose FROM key_metadata WHERE key_id=?", in.KeyID).Scan(&keyPurpose)
	if e != nil {
		return release.Binding{}, e
	}
	if keyPurpose != purpose {
		return release.Binding{}, ErrKey
	}
	if purpose == "serving" {
		return g.LockActive(ctx, tx, in.Profile.CRUID)
	}
	if purpose != "validation" || in.ValidationIntentID == "" {
		return release.Binding{}, ErrPolicy
	}
	var binding release.Binding
	var closed, tombstone bool
	var mode, active string
	e = tx.QueryRowContext(ctx, `SELECT p.publication_id,p.revision,p.generation,p.activation_epoch,l.tombstone,l.desired_mode,p.state FROM release_links l JOIN publications p ON p.cluster_id=l.cluster_id AND p.publication_id=l.candidate_id WHERE l.cluster_id=? AND l.cr_uid=? FOR SHARE NOWAIT`, s.cluster, in.Profile.CRUID).Scan(&binding.PublicationID, &binding.Revision, &binding.Generation, &binding.Epoch, &tombstone, &mode, &active)
	_ = closed
	if e != nil {
		return binding, e
	}
	if tombstone || mode != "Published" || active != "Candidate" || binding != in.Profile.Binding {
		return binding, ErrConflict
	}
	t, e := now(ctx, tx)
	if e != nil {
		return binding, e
	}
	var request, key, profile string
	e = tx.QueryRowContext(ctx, "SELECT request_id,key_id,profile_sha256 FROM validation_intents WHERE intent_id=? AND publication_id=? AND revoked=FALSE AND expires_at>?", in.ValidationIntentID, binding.PublicationID, t).Scan(&request, &key, &profile)
	if e != nil || request != in.RequestID || key != in.KeyID || profile != hash(in.Profile) {
		return binding, ErrConflict
	}
	proofs, e := (DurableProofs{Cluster: s.cluster}).Publication(ctx, tx, mysqlstore.Publication{Binding: binding, CRUID: in.Profile.CRUID})
	if e != nil {
		return binding, e
	}
	if !proofs.RuntimeReady || !proofs.GatewayApplied {
		return binding, release.ErrDependencyMissing
	}
	return binding, nil
}
func purposeOf(in Input) string {
	if in.Purpose == "" {
		return "serving"
	}
	return in.Purpose
}
