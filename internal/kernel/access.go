package kernel

import (
	"context"
	"database/sql"
)

// Profile reads immutable metadata; it never authorizes a model invocation.
func (s *Store) Profile(ctx context.Context, id string) (Profile, error) {
	var out Profile
	e := s.tx(ctx, func(tx *sql.Tx) error { var e error; out, e = s.profile(ctx, tx, id); return e })
	return out, e
}
