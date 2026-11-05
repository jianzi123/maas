package kernel

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

//go:embed schema/0001_kernel.sql
var migration string

// Migrate is an explicit administrator action. The operator never calls it.
// An Applying record permits restart after independently committed MySQL DDL.
func Migrate(ctx context.Context, db *sql.DB) error {
	if e := migrateBase(ctx, db); e != nil {
		return e
	}
	return migrateControl(ctx, db)
}
func migrateBase(ctx context.Context, db *sql.DB) error {
	c, e := db.Conn(ctx)
	if e != nil {
		return ErrUnavailable
	}
	defer c.Close()
	var locked int
	if e = c.QueryRowContext(ctx, "SELECT GET_LOCK(CONCAT('maas-kernel:',DATABASE()),0)").Scan(&locked); e != nil || locked != 1 {
		return ErrBusy
	}
	defer c.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-kernel:',DATABASE()))")
	if _, e = c.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS kernel_schema_migrations(version INT PRIMARY KEY,sha256 CHAR(64) NOT NULL,state ENUM('Applying','Applied') NOT NULL) ENGINE=InnoDB`); e != nil {
		return sanitize(e)
	}
	var digest, state string
	e = c.QueryRowContext(ctx, "SELECT sha256,state FROM kernel_schema_migrations WHERE version=1").Scan(&digest, &state)
	want := fmt.Sprintf("%x", sha256.Sum256([]byte(migration)))
	if e == nil {
		if digest != want {
			return ErrConflict
		}
		if state == "Applied" {
			return nil
		}
	} else if errors.Is(e, sql.ErrNoRows) {
		var n int
		if e = c.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('kernel_guard','platform_keys','budget_windows','rate_window_grants','invocation_profiles','generation_requests','concurrency_slots','usage_events','usage_daily','slot_release_log')`).Scan(&n); e != nil {
			return sanitize(e)
		}
		if n != 0 {
			return ErrConflict
		}
		if _, e = c.ExecContext(ctx, "INSERT INTO kernel_schema_migrations VALUES(1,?,'Applying')", want); e != nil {
			return sanitize(e)
		}
	} else {
		return sanitize(e)
	}
	for _, q := range strings.Split(migration, ";") {
		if q = strings.TrimSpace(q); q != "" {
			if _, e = c.ExecContext(ctx, q); e != nil {
				return sanitize(e)
			}
		}
	}
	_, e = c.ExecContext(ctx, "UPDATE kernel_schema_migrations SET state='Applied' WHERE version=1 AND sha256=?", want)
	return sanitize(e)
}
func sanitize(e error) error {
	if e == nil {
		return nil
	}
	for _, known := range []error{ErrDiagnosticLimit, ErrNotFound, ErrUnavailable, ErrBusy, ErrConflict, ErrKey, ErrBudget, ErrTokens, ErrMoney, ErrCapacity, ErrBound, ErrPrice, ErrPolicy, ErrCommitUnknown, release.ErrDependencyMissing, release.ErrConflict} {
		if errors.Is(e, known) {
			return known
		}
	}
	var m *mysql.MySQLError
	if errors.As(e, &m) {
		if m.Number == 1062 {
			return ErrConflict
		}
		if m.Number == 1205 || m.Number == 1213 || m.Number == 3572 {
			return ErrBusy
		}
	}
	return ErrUnavailable
}
func now(ctx context.Context, tx *sql.Tx) (time.Time, error) {
	var t time.Time
	e := tx.QueryRowContext(ctx, "SELECT UTC_TIMESTAMP(6)").Scan(&t)
	return t, e
}
func (s *Store) tx(ctx context.Context, fn func(*sql.Tx) error) error {
	tx, e := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if e != nil {
		return sanitize(e)
	}
	defer tx.Rollback()
	if e = fn(tx); e != nil {
		return sanitize(e)
	}
	if e = tx.Commit(); e != nil {
		return ErrCommitUnknown
	}
	return nil
}
func (s *Store) guard(ctx context.Context, tx *sql.Tx, mode string) (RatePolicy, error) {
	var p RatePolicy
	var cluster string
	e := tx.QueryRowContext(ctx, "SELECT cluster_id,rate_revision,rate_epoch,rate_ready,window_ms,global_limit,key_limit FROM kernel_guard WHERE id=1 "+mode).Scan(&cluster, &p.Revision, &p.Epoch, &p.Ready, &p.WindowMS, &p.GlobalLimit, &p.KeyLimit)
	if e == nil && cluster != s.cluster {
		return p, ErrUnavailable
	}
	return p, e
}
func (s *Store) LockCapacity(ctx context.Context, tx *sql.Tx) error {
	_, e := s.guard(ctx, tx, "FOR SHARE NOWAIT")
	return e
}
func (s *Store) PublicationEvidence(ctx context.Context, tx *sql.Tx, p mysqlstore.Publication) (mysqlstore.Evidence, error) {
	if s.proofs == nil {
		return mysqlstore.Evidence{}, release.ErrDependencyMissing
	}
	profile, e := s.profile(ctx, tx, p.PublicationID)
	if e != nil {
		if errors.Is(e, sql.ErrNoRows) {
			return mysqlstore.Evidence{}, release.ErrDependencyMissing
		}
		return mysqlstore.Evidence{}, e
	}
	if profile.Binding != p.Binding || profile.CRUID != p.CRUID {
		return mysqlstore.Evidence{}, release.ErrDependencyMissing
	}
	result, e := s.proofs.Publication(ctx, tx, p)
	if e != nil {
		return result, e
	}
	// AccountingReady is derived from the real installed schema/guard/capacity,
	// never a gateway self-report or a test-core table.
	var slots int
	if e = tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM concurrency_slots").Scan(&slots); e != nil {
		return result, e
	}
	result.AccountingReady = result.AccountingReady && slots > 0
	return result, nil
}
func (s *Store) DrainEvidence(ctx context.Context, tx *sql.Tx, uid string, pubs []mysqlstore.Publication) (mysqlstore.DrainEvidence, error) {
	out := mysqlstore.DrainEvidence{CRUID: uid, Verified: true, Publications: []string{}}
	t, e := now(ctx, tx)
	if e != nil {
		return out, e
	}
	out.FreshUntil = t.Add(time.Second)
	for _, p := range pubs {
		if p.CRUID != uid {
			return out, ErrConflict
		}
		out.Publications = append(out.Publications, p.PublicationID)
		var n int64
		if e = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM generation_requests WHERE publication_id=? AND result='in_progress'`, p.PublicationID).Scan(&n); e != nil {
			return out, e
		}
		out.InProgress += n
		for _, state := range []string{"HELD", "QUARANTINED"} {
			if e = tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM concurrency_slots WHERE publication_id=? AND state=?", p.PublicationID, state).Scan(&n); e != nil {
				return out, e
			}
			if state == "HELD" {
				out.HeldSlots += n
			} else {
				out.QuarantinedSlots += n
			}
		}
	}
	return out, nil
}

// Configure is explicit installation setup. It never resets existing slots,
// budgets or rate witnesses. Redis reconstruction must use BlockRate/ReadyRate.
func (s *Store) Configure(ctx context.Context, p RatePolicy, slots int64) error {
	if p.Revision == "" || p.Epoch < 1 || p.WindowMS < 1 || p.GlobalLimit < 1 || p.KeyLimit < 1 || slots < 1 || slots > 10000 {
		return ErrPolicy
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		var existing int
		if e := tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM kernel_guard").Scan(&existing); e != nil {
			return e
		}
		if existing != 0 {
			return ErrConflict
		}
		if _, e := tx.ExecContext(ctx, "INSERT INTO kernel_guard VALUES(1,?,?,?,?,?,?,?)", s.cluster, p.Revision, p.Epoch, false, p.WindowMS, p.GlobalLimit, p.KeyLimit); e != nil {
			return e
		}
		for i := int64(1); i <= slots; i++ {
			if _, e := tx.ExecContext(ctx, "INSERT INTO concurrency_slots(slot_id,state) VALUES(?,'FREE')", i); e != nil {
				return e
			}
		}
		return nil
	})
}
func (s *Store) BlockRate(ctx context.Context) (int64, error) {
	var epoch int64
	e := s.tx(ctx, func(tx *sql.Tx) error {
		p, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT")
		if e != nil {
			return e
		}
		if p.Epoch >= maxCounter {
			return ErrConflict
		}
		epoch = p.Epoch + 1
		_, e = tx.ExecContext(ctx, "UPDATE kernel_guard SET rate_ready=FALSE,rate_epoch=? WHERE id=1", epoch)
		return e
	})
	return epoch, e
}

// ReadyRate is called by an installation coordinator only AFTER reconstructing
// Redis from durable grants outside the transaction. No automatic empty recovery.
func (s *Store) ReadyRate(ctx context.Context, epoch int64) error {
	return s.tx(ctx, func(tx *sql.Tx) error {
		p, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT")
		if e != nil {
			return e
		}
		if epoch != p.Epoch {
			return ErrConflict
		}
		_, e = tx.ExecContext(ctx, "UPDATE kernel_guard SET rate_ready=TRUE WHERE id=1")
		return e
	})
}
func (s *Store) verifier(raw string) string {
	h := hmac.New(sha256.New, s.pepper)
	h.Write([]byte(raw))
	return hex.EncodeToString(h.Sum(nil))
}
func (s *Store) CreateKey(ctx context.Context, p Policy) (string, string, error) {
	return s.createKey(ctx, "platform-key", p, "serving")
}
func (s *Store) createKey(ctx context.Context, name string, p Policy, purpose string) (id, raw string, err error) {
	if err = validatePolicy(p); err != nil {
		return
	}
	id = uuid.NewString()
	b := make([]byte, 32)
	if _, err = rand.Read(b); err != nil {
		return
	}
	raw = "maas_" + base64.RawURLEncoding.EncodeToString(b)
	err = s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		data, _ := json.Marshal(p)
		var currency *string
		if p.Limits.Money != nil {
			currency = &p.Limits.Money.Currency
		}
		_, e := tx.ExecContext(ctx, "INSERT INTO platform_keys(key_id,verifier,key_epoch,policy_json,retained_currency) VALUES(?,?,1,?,?)", id, s.verifier(raw), data, currency)
		if e != nil {
			return e
		}
		_, e = tx.ExecContext(ctx, "INSERT INTO key_metadata(key_id,name,key_prefix,created_at,purpose) VALUES(?,?,?,UTC_TIMESTAMP(6),?)", id, name, raw[:13], purpose)
		return e
	})
	if err != nil {
		raw = ""
	}
	return
}
func (s *Store) Authenticate(ctx context.Context, raw string) (string, int64, error) {
	if len(raw) < 40 || len(raw) > 128 {
		return "", 0, ErrKey
	}
	var id string
	var epoch int64
	var revoked, blocked bool
	e := s.db.QueryRowContext(ctx, "SELECT key_id,key_epoch,revoked,blocked FROM platform_keys WHERE verifier=?", s.verifier(raw)).Scan(&id, &epoch, &revoked, &blocked)
	if errors.Is(e, sql.ErrNoRows) || revoked {
		return "", 0, ErrKey
	}
	if e != nil {
		return "", 0, ErrUnavailable
	}
	if blocked {
		return "", 0, ErrBound
	}
	return id, epoch, nil
}
func (s *Store) Revoke(ctx context.Context, id string) error {
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		var epoch int64
		var revoked bool
		if e := tx.QueryRowContext(ctx, "SELECT key_epoch,revoked FROM platform_keys WHERE key_id=? FOR UPDATE NOWAIT", id).Scan(&epoch, &revoked); e != nil {
			if errors.Is(e, sql.ErrNoRows) {
				return ErrNotFound
			}
			return e
		}
		if revoked {
			return nil
		}
		if epoch >= maxCounter {
			return ErrConflict
		}
		_, e := tx.ExecContext(ctx, "UPDATE platform_keys SET revoked=TRUE,key_epoch=key_epoch+1 WHERE key_id=?", id)
		if e != nil {
			return e
		}
		_, e = tx.ExecContext(ctx, "UPDATE key_metadata SET revoked_at=UTC_TIMESTAMP(6) WHERE key_id=?", id)
		return e
	})
}
func (s *Store) UpdatePolicy(ctx context.Context, id string, p Policy) error {
	if e := validatePolicy(p); e != nil {
		return e
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		old, _, e := s.key(ctx, tx, id)
		if e != nil {
			return e
		}
		var retained sql.NullString
		if e = tx.QueryRowContext(ctx, "SELECT retained_currency FROM platform_keys WHERE key_id=?", id).Scan(&retained); e != nil {
			return e
		}
		if old.Window != p.Window || (retained.Valid && p.Limits.Money != nil && retained.String != p.Limits.Money.Currency) {
			return ErrPolicy
		}
		b, _ := json.Marshal(p)
		var currency *string
		if p.Limits.Money != nil {
			currency = &p.Limits.Money.Currency
		}
		_, e = tx.ExecContext(ctx, "UPDATE platform_keys SET policy_json=?,retained_currency=COALESCE(retained_currency,?) WHERE key_id=?", b, currency, id)
		return e
	})
}
func (s *Store) key(ctx context.Context, tx *sql.Tx, id string) (Policy, int64, error) {
	var p Policy
	var epoch int64
	var revoked, blocked bool
	var b []byte
	e := tx.QueryRowContext(ctx, "SELECT policy_json,key_epoch,revoked,blocked FROM platform_keys WHERE key_id=? FOR UPDATE NOWAIT", id).Scan(&b, &epoch, &revoked, &blocked)
	if errors.Is(e, sql.ErrNoRows) {
		return p, 0, ErrNotFound
	}
	if e != nil {
		return p, 0, e
	}
	if revoked {
		return p, epoch, ErrKey
	}
	if blocked {
		return p, epoch, ErrBound
	}
	e = json.Unmarshal(b, &p)
	return p, epoch, e
}
func (s *Store) RegisterProfile(ctx context.Context, p Profile) error {
	if !validUUID(p.CRUID) || !validUUID(p.Binding.PublicationID) || !validUUID(p.SourceID) || p.ApprovalRef == "" || p.Alias == "" || p.RouteDigest == "" || p.GatewayEpoch < 1 {
		return ErrPolicy
	}
	if p.Price != nil && (validatePrice(p.Price) != nil || p.Price.Source != p.SourceID || p.Price.Model != p.UpstreamModel) {
		return ErrPrice
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		var blocked int
		if e := tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM invocation_profiles WHERE blocked=TRUE AND JSON_UNQUOTE(JSON_EXTRACT(snapshot_json,'$.CapabilityRevision'))=?`, p.CapabilityRevision).Scan(&blocked); e != nil {
			return e
		}
		if blocked != 0 {
			return ErrBound
		}
		var b release.Binding
		var uid, ns, name, alias string
		e := tx.QueryRowContext(ctx, `SELECT p.publication_id,p.revision,p.generation,p.activation_epoch,p.cr_uid,l.namespace,l.name,l.model_alias FROM publications p JOIN release_links l ON l.cluster_id=p.cluster_id AND l.cr_uid=p.cr_uid WHERE p.cluster_id=? AND p.publication_id=? FOR SHARE NOWAIT`, s.cluster, p.Binding.PublicationID).Scan(&b.PublicationID, &b.Revision, &b.Generation, &b.Epoch, &uid, &ns, &name, &alias)
		if e != nil {
			return e
		}
		if p.Binding != b || p.CRUID != uid || p.Namespace != ns || p.Name != name || p.Alias != alias {
			return ErrConflict
		}
		var oldHash string
		e = tx.QueryRowContext(ctx, "SELECT snapshot_sha256 FROM invocation_profiles WHERE publication_id=?", b.PublicationID).Scan(&oldHash)
		if e == nil {
			if oldHash == hash(p) {
				return nil
			}
			return ErrConflict
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		data, _ := json.Marshal(p)
		_, e = tx.ExecContext(ctx, "INSERT INTO invocation_profiles(publication_id,snapshot_json,snapshot_sha256) VALUES(?,?,?)", b.PublicationID, data, hash(p))
		return e
	})
}
func validUUID(v string) bool { u, e := uuid.Parse(v); return e == nil && u.String() == v }
func (s *Store) profile(ctx context.Context, tx *sql.Tx, id string) (Profile, error) {
	var p Profile
	var data []byte
	var blocked bool
	var digest string
	e := tx.QueryRowContext(ctx, "SELECT snapshot_json,snapshot_sha256,blocked FROM invocation_profiles WHERE publication_id=? FOR SHARE NOWAIT", id).Scan(&data, &digest, &blocked)
	if e != nil {
		return p, e
	}
	if blocked {
		return p, ErrBound
	}
	if e = json.Unmarshal(data, &p); e != nil {
		return p, e
	}
	if hash(p) != digest {
		return p, ErrConflict
	}
	return p, nil
}
func (s *Store) ReadRequest(ctx context.Context, id string) (Snapshot, string, error) {
	var snap Snapshot
	var b []byte
	var state string
	var owner string
	var fence int64
	e := s.db.QueryRowContext(ctx, "SELECT snapshot_json,result,owner_id,owner_fence FROM generation_requests WHERE request_id=?", id).Scan(&b, &state, &owner, &fence)
	if e != nil {
		return snap, state, sanitize(e)
	}
	if e = json.Unmarshal(b, &snap); e != nil {
		return snap, state, ErrUnavailable
	}
	snap.Input.Owner = owner
	snap.OwnerFence = fence
	return snap, state, nil
}
