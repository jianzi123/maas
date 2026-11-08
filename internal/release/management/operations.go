// Package management owns durable administrative operations, never inference.
package management

import (
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
)

//go:embed schema.sql
var migration string

// Migrate is explicit and uses the same administrative migration lock. Published
// release migrations 1/2 and the internal command ledger are left unchanged.
func Migrate(ctx context.Context, db *sql.DB) error {
	c, e := db.Conn(ctx)
	if e != nil {
		return history.ErrUnavailable
	}
	defer c.Close()
	var name string
	if c.QueryRowContext(ctx, "SELECT DATABASE()").Scan(&name) != nil || name == "" {
		return history.ErrUnavailable
	}
	lock := "maas-release:" + release.Hash(name)[:40]
	var n int
	if c.QueryRowContext(ctx, "SELECT GET_LOCK(?,0)", lock).Scan(&n) != nil || n != 1 {
		return history.ErrConflict
	}
	defer c.ExecContext(context.Background(), "SELECT RELEASE_LOCK(?)", lock)
	sum := sha256.Sum256([]byte(migration))
	want := hex.EncodeToString(sum[:])
	var old, state string
	e = c.QueryRowContext(ctx, "SELECT sha256,state FROM release_schema_migrations WHERE version=3").Scan(&old, &state)
	if e == nil {
		if old != want {
			return history.ErrConflict
		}
		if state == "Applied" {
			return nil
		}
	} else if errors.Is(e, sql.ErrNoRows) {
		if c.QueryRowContext(ctx, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='release_management_operations'").Scan(&n) != nil {
			return history.ErrUnavailable
		}
		if n != 0 {
			return history.ErrConflict
		}
		if _, e = c.ExecContext(ctx, "INSERT INTO release_schema_migrations VALUES(3,?,'Applying')", want); e != nil {
			return history.ErrUnavailable
		}
	} else {
		return history.ErrUnavailable
	}
	for _, q := range strings.Split(migration, ";") {
		if strings.TrimSpace(q) != "" {
			if _, e = c.ExecContext(ctx, q); e != nil {
				return history.ErrUnavailable
			}
		}
	}
	_, e = c.ExecContext(ctx, "UPDATE release_schema_migrations SET state='Applied' WHERE version=3 AND sha256=?", want)
	if e != nil {
		return history.ErrUnavailable
	}
	return nil
}

type Operations struct {
	DB      *sql.DB
	Cluster string
	Access  history.Access
}
type record struct {
	Operation                api.Operation
	Scope, SpecHash, Version string
	Acknowledged             bool
}

func specHash(s api.Spec) string {
	b, _ := json.Marshal(s)
	v := sha256.Sum256(b)
	return hex.EncodeToString(v[:])
}
func validID(s string) bool { v, e := uuid.Parse(s); return e == nil && v.String() == s }

// Begin records an Unknown sentinel BEFORE any K8s send. There is no recovery
// dispatcher: a crash, DB ACK loss, or K8s ACK loss can never replay this intent.
func (o *Operations) begin(ctx context.Context, action, scope, ns, name, uid, rv string, spec api.Spec) (api.Operation, bool, error) {
	id := uuid.NewString()
	tx, e := o.DB.BeginTx(ctx, nil)
	if e != nil {
		return api.Operation{}, false, history.ErrUnavailable
	}
	defer tx.Rollback()
	var expected any
	if uid != "" {
		expected = uid
	}
	_, e = tx.ExecContext(ctx, `INSERT INTO release_management_operations(cluster_id,operation_id,scope_id,namespace,name,action,desired_state,cr_uid,expected_rv,spec_sha256,state,reason) VALUES(?,?,?,?,?,?,?,?,?,?,'Unknown','WriteOutcomeUnknown')`, o.Cluster, id, scope, ns, name, action, spec.Lifecycle.DesiredState, expected, rv, specHash(spec))
	if e != nil {
		return api.Operation{}, false, history.ErrUnavailable
	}
	committed := tx.Commit() == nil
	// Even after an unknown INSERT ACK we only read this ID, never dispatch it.
	readCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	r, e := o.load(readCtx, id)
	if e != nil {
		return api.Operation{}, false, e
	}
	return r.Operation, committed, nil
}

func (o *Operations) load(ctx context.Context, id string) (record, error) {
	var r record
	var uid, pub, reason sql.NullString
	var gen sql.NullInt64
	var created, updated time.Time
	e := o.DB.QueryRowContext(ctx, `SELECT operation_id,action,state,namespace,name,cr_uid,requested_generation,publication_id,created_at,updated_at,reason,scope_id,spec_sha256,expected_rv,acknowledged FROM release_management_operations WHERE cluster_id=? AND operation_id=?`, o.Cluster, id).Scan(&r.Operation.ID, &r.Operation.Action, &r.Operation.State, &r.Operation.Namespace, &r.Operation.Name, &uid, &gen, &pub, &created, &updated, &reason, &r.Scope, &r.SpecHash, &r.Version, &r.Acknowledged)
	if errors.Is(e, sql.ErrNoRows) {
		return r, history.ErrNotFound
	}
	if e != nil {
		return r, history.ErrUnavailable
	}
	if uid.Valid {
		r.Operation.CRUID = &uid.String
	}
	if gen.Valid {
		r.Operation.RequestedGeneration = &gen.Int64
	}
	if pub.Valid {
		r.Operation.PublicationID = &pub.String
	}
	if reason.Valid {
		r.Operation.Reason = &reason.String
	}
	r.Operation.CreatedAt.Time = created.UTC()
	r.Operation.UpdatedAt.Time = updated.UTC()
	r.Operation.Message = "Management intent; publication and admission are independently reconciled."
	return r, nil
}
func (o *Operations) Read(ctx context.Context, id string) (map[string]any, error) {
	if o == nil || o.DB == nil || o.Access == nil {
		return nil, history.ErrUnavailable
	}
	if !validID(id) {
		return nil, history.ErrInvalid
	}
	r, e := o.load(ctx, id)
	if e != nil {
		return nil, e
	}
	uid := ""
	if r.Operation.CRUID != nil {
		uid = *r.Operation.CRUID
	}
	scope, e := o.Access.Scope(ctx, r.Operation.Namespace, r.Operation.Name, uid)
	if e != nil {
		return nil, e
	}
	if scope != r.Scope {
		return nil, history.ErrNotFound
	}
	if r.Acknowledged && r.Operation.State == "Running" {
		if e = o.refreshKnown(ctx, id); e != nil {
			return nil, e
		}
		r, e = o.load(ctx, id)
		if e != nil {
			return nil, e
		}
	}
	return object(r.Operation), nil
}
func object(v any) map[string]any {
	b, _ := json.Marshal(v)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	return m
}

func (o *Operations) finishWrite(ctx context.Context, id string, m *api.ModelRelease, writeErr error) error {
	state := "Running"
	var reason any
	var uid, gen any
	ack := writeErr == nil
	if ack && m != nil && m.UID != "" {
		uid = string(m.UID)
	}
	if ack && m != nil && m.Generation > 0 {
		gen = m.Generation
	}
	if writeErr != nil {
		state = "Unknown"
		reason = "WriteOutcomeUnknown"
		if errors.Is(writeErr, history.ErrConflict) {
			state = "Failed"
			reason = "RevisionConflict"
		}
		if errors.Is(writeErr, history.ErrForbidden) {
			state = "Failed"
			reason = "Forbidden"
		}
		if errors.Is(writeErr, history.ErrInvalid) {
			state = "Failed"
			reason = "InvalidSpec"
		}
	}
	_, e := o.DB.ExecContext(ctx, `UPDATE release_management_operations SET state=?,reason=?,acknowledged=?,cr_uid=COALESCE(?,cr_uid),requested_generation=?,updated_at=UTC_TIMESTAMP(6) WHERE cluster_id=? AND operation_id=? AND state='Unknown' AND acknowledged=FALSE`, state, reason, ack, uid, gen, o.Cluster, id)
	if e != nil {
		return history.ErrUnavailable
	}
	return nil
}

// Only acknowledged original writes can advance from Running. These joins read
// the existing publisher's durable result for the exact UID/generation/spec;
// they never inspect current CR contents to guess a lost mutation's outcome.
// Succeeded means this operation's durable lifecycle result, not current Callable.
func (o *Operations) refreshKnown(ctx context.Context, id string) error {
	// A consistent non-locking read observes the original lifecycle result. Then
	// CAS only the projection row: a GET must not take release locks after an
	// operation lock and deadlock with the publisher's release -> operation order.
	var pub sql.NullString
	e := o.DB.QueryRowContext(ctx, `SELECT IF(o.desired_state='Paused' OR o.action='Delete',NULL,p.publication_id) `+completionJoins+` WHERE o.cluster_id=? AND o.operation_id=? AND `+completionPredicate, o.Cluster, id).Scan(&pub)
	if errors.Is(e, sql.ErrNoRows) {
		return nil
	}
	if e != nil {
		return history.ErrUnavailable
	}
	var publication any
	if pub.Valid {
		publication = pub.String
	}
	_, e = o.DB.ExecContext(ctx, `UPDATE release_management_operations SET state='Succeeded',reason=NULL,publication_id=?,updated_at=UTC_TIMESTAMP(6) WHERE cluster_id=? AND operation_id=? AND state='Running' AND acknowledged=TRUE`, publication, o.Cluster, id)
	if e != nil {
		return history.ErrUnavailable
	}
	return nil
}

const completionJoins = `FROM release_management_operations o JOIN release_links l ON l.cluster_id=o.cluster_id AND l.cr_uid=o.cr_uid AND l.namespace=o.namespace AND l.name=o.name AND (l.last_observed_generation=o.requested_generation OR (o.action='Delete' AND l.last_observed_generation>=o.requested_generation)) LEFT JOIN publications p ON p.cluster_id=l.cluster_id AND p.publication_id=l.active_id LEFT JOIN retained_release_snapshots h ON h.cluster_id=l.cluster_id AND h.cr_uid=l.cr_uid AND h.revision=p.revision`
const completionPredicate = `o.state='Running' AND o.acknowledged=TRUE AND ((o.desired_state='Paused' AND o.action<>'Delete' AND l.desired_mode='Paused' AND l.admission_closed=TRUE AND l.cleanup_complete=TRUE AND l.tombstone=FALSE) OR (o.action='Delete' AND l.desired_mode='Deleting' AND l.admission_closed=TRUE AND l.cleanup_complete=TRUE AND l.tombstone=TRUE) OR (o.action<>'Delete' AND o.desired_state='Published' AND l.desired_mode='Published' AND l.admission_closed=FALSE AND l.tombstone=FALSE AND p.state='Active' AND p.activated=TRUE AND p.generation=o.requested_generation AND h.spec_sha256=o.spec_sha256))`

type executor interface {
	ExecContext(context.Context, string, ...any) (sql.Result, error)
}

// CompleteInTransaction is an opt-in publisher hook. Record operation completion
// in the SAME publication/cleanup transaction so a later update cannot erase the
// original terminal result before the browser queries it.
func CompleteInTransaction(ctx context.Context, tx *sql.Tx, cluster, uid string) error {
	return complete(ctx, tx, cluster, "o.cr_uid", uid)
}
func complete(ctx context.Context, db executor, cluster, column, value string) error {
	_, e := db.ExecContext(ctx, `UPDATE `+strings.TrimPrefix(completionJoins, "FROM ")+` SET o.state='Succeeded',o.reason=NULL,o.publication_id=IF(o.desired_state='Paused' OR o.action='Delete',NULL,p.publication_id),o.updated_at=UTC_TIMESTAMP(6) WHERE o.cluster_id=? AND `+column+`=? AND `+completionPredicate, cluster, value)
	if e != nil {
		return history.ErrUnavailable
	}
	return nil
}
