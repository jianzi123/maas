package kernel

import (
	"context"
	"database/sql"
)

// AdmissionConfiguration reads current policy for preparing the original ticket.
// The authenticated Higress Authorizer still performs the only Admit transaction.
func (s *Store) AdmissionConfiguration(ctx context.Context, id string) (Policy, RatePolicy, error) {
	var policy Policy
	var rate RatePolicy
	e := s.tx(ctx, func(tx *sql.Tx) error {
		var e error
		rate, e = s.guard(ctx, tx, "FOR SHARE NOWAIT")
		if e != nil {
			return e
		}
		policy, _, e = s.key(ctx, tx, id)
		return e
	})
	return policy, rate, e
}

// Profile reads immutable metadata; it never authorizes a model invocation.
func (s *Store) Profile(ctx context.Context, id string) (Profile, error) {
	var out Profile
	e := s.tx(ctx, func(tx *sql.Tx) error { var e error; out, e = s.profile(ctx, tx, id); return e })
	return out, e
}
