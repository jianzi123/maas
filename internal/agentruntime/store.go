package agentruntime

import (
	"context"
	"database/sql"
	_ "embed"
	"encoding/json"
	"errors"

	mysql "github.com/go-sql-driver/mysql"
)

// MySQLStore uses optimistic revisions, so two replicas cannot claim one run.
// A single aggregate keeps message, checkpoint and event commits indivisible.
type MySQLStore struct{ DB *sql.DB }

//go:embed migrations/001_sessions.sql
var Migration string

func Migrate(ctx context.Context, db *sql.DB) error { _, e := db.ExecContext(ctx, Migration); return e }
func (s MySQLStore) Get(ctx context.Context, id string) (Session, error) {
	var b []byte
	var v Session
	e := s.DB.QueryRowContext(ctx, "SELECT document FROM agent_sessions_v1 WHERE session_id=?", id).Scan(&b)
	if errors.Is(e, sql.ErrNoRows) {
		return v, ErrNotFound
	}
	if e != nil {
		return v, e
	}
	if json.Unmarshal(b, &v) != nil || v.Version != Version {
		return v, ErrUnavailable
	}
	return v, nil
}
func (s MySQLStore) List(ctx context.Context, owner string) ([]Session, error) {
	rows, e := s.DB.QueryContext(ctx, "SELECT document FROM agent_sessions_v1 WHERE owner_id=? ORDER BY session_id LIMIT 200", owner)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Session{}
	for rows.Next() {
		var b []byte
		var v Session
		if e = rows.Scan(&b); e != nil {
			return nil, e
		}
		if json.Unmarshal(b, &v) != nil || v.Version != Version {
			return nil, ErrUnavailable
		}
		if !v.Deleted {
			out = append(out, v)
		}
	}
	return out, rows.Err()
}
func (s MySQLStore) CompareAndSwap(ctx context.Context, v Session, expected int64) error {
	if v.Revision != expected+1 || v.Version != Version {
		return ErrInvalid
	}
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	if len(b) > 32<<20 {
		return ErrInvalid
	}
	if expected == 0 {
		_, e = s.DB.ExecContext(ctx, "INSERT INTO agent_sessions_v1(session_id,owner_id,revision,document) VALUES(?,?,?,?)", v.ID, v.Owner, v.Revision, b)
		var duplicate *mysql.MySQLError
		if errors.As(e, &duplicate) && duplicate.Number == 1062 {
			return ErrConflict
		}
		return e
	}
	r, e := s.DB.ExecContext(ctx, "UPDATE agent_sessions_v1 SET revision=?,document=? WHERE session_id=? AND owner_id=? AND revision=?", v.Revision, b, v.ID, v.Owner, expected)
	if e != nil {
		return e
	}
	n, e := r.RowsAffected()
	if e != nil {
		return e
	}
	if n != 1 {
		return ErrConflict
	}
	return nil
}
