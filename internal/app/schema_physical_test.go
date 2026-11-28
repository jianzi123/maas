package app

import (
	"context"
	"net/http/httptest"
	"testing"
)

// Independent fault injection keeps every journal/hash Applied, and mutates
// only this fixture's objects. No serving path may recreate the missing shape.
func TestProductPhysicalGateRejectsMissingObjectsAndTerminalKeys(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	cases := []struct{ name, damage, restore string }{
		{"missing_usage_events", "RENAME TABLE usage_events TO saved_shape_usage_events", "RENAME TABLE saved_shape_usage_events TO usage_events"},
		{"missing_only_terminal", "ALTER TABLE usage_events DROP INDEX only_terminal", "ALTER TABLE usage_events ADD UNIQUE KEY only_terminal(request_id,event_type)"},
		{"missing_private_history", "RENAME TABLE retained_release_snapshots TO saved_shape_snapshots", "RENAME TABLE saved_shape_snapshots TO retained_release_snapshots"},
		{"nonunique_terminal_key", "ALTER TABLE usage_events DROP INDEX only_terminal, ADD INDEX only_terminal(request_id,event_type)", "ALTER TABLE usage_events DROP INDEX only_terminal, ADD UNIQUE KEY only_terminal(request_id,event_type)"},
		{"partial_terminal_key", "ALTER TABLE usage_events DROP INDEX only_terminal, ADD UNIQUE KEY only_terminal(request_id(8),event_type(8))", "ALTER TABLE usage_events DROP INDEX only_terminal, ADD UNIQUE KEY only_terminal(request_id,event_type)"},
		{"wrong_terminal_column_order", "ALTER TABLE usage_events DROP INDEX only_terminal, ADD UNIQUE KEY only_terminal(event_type,request_id)", "ALTER TABLE usage_events DROP INDEX only_terminal, ADD UNIQUE KEY only_terminal(request_id,event_type)"},
		{"nullable_terminal_identity", "ALTER TABLE usage_events MODIFY event_type VARCHAR(32) NULL", "ALTER TABLE usage_events MODIFY event_type VARCHAR(32) NOT NULL"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			running, e := Open(ctx, c)
			if e != nil {
				t.Fatal("positive control", e)
			}
			defer running.Close()
			if _, e = db.Exec(tc.damage); e != nil {
				t.Fatal(e)
			}
			restored := false
			defer func() {
				if !restored {
					db.Exec(tc.restore)
				}
			}()
			opened, e := Open(ctx, c)
			if e == nil {
				opened.Close()
				t.Fatal("bad physical schema reached ownership/listener")
			}
			if e.Error() != errPhysicalSchema.Error() {
				t.Fatal("wrong failure boundary", e)
			}
			response := httptest.NewRecorder()
			running.Handler.ServeHTTP(response, httptest.NewRequest("GET", "/readyz", nil))
			if response.Code != 503 || running.ctx.Err() == nil {
				t.Fatal("running owner stayed ready", response.Code)
			}
			running.Close()
			if _, e = db.Exec(tc.restore); e != nil {
				t.Fatal(e)
			}
			restored = true
			recovered, e := Open(ctx, c)
			if e != nil {
				t.Fatal("explicitly restored schema rejected", e)
			}
			recovered.Close()
			var applied int
			if e = db.QueryRow("SELECT COUNT(*) FROM product_schema_migrations WHERE state='Applied'").Scan(&applied); e != nil || applied != 2 {
				t.Fatal("gate changed migration markers", applied, e)
			}
		})
	}
}
