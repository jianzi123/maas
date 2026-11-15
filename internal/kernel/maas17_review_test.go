package kernel

import (
	"context"
	"database/sql"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

// Review overlay only: no source file or production adapter is replaced.
// The expected oracle rejects protocol failure and observes cancellation before
// terminal commit. A failed assertion is retained as a review counterexample.
func TestMAAS17StreamAudit(t *testing.T) {
	for _, mode := range []string{"normal", "data_error_then_finish", "content_after_finish", "cancel_after_finish_write"} {
		t.Run(mode, func(t *testing.T) {
			f := setupUsagePolicy(t, 1, &UsagePolicy{"maas17-controlled-fixture", "final_only"})
			in := f.input(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				calls++
				if _, err := f.core.Admit(req.Context(), f.gate, in); err != nil {
					t.Errorf("admit: %v", err)
					w.WriteHeader(503)
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"answer\"}}]}\n\n")
				if mode == "data_error_then_finish" {
					io.WriteString(w, "data: {\"error\":{\"message\":\"synthetic upstream failure\",\"code\":\"failure\"}}\n\n")
				}
				io.WriteString(w, diagnosticFrame)
				io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n")
				if mode == "content_after_finish" {
					io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"AFTER_FINISH\"}}]}\n\n")
				}
				io.WriteString(w, "data: [DONE]\n\n")
			}))
			defer server.Close()
			out := httptest.NewRecorder()
			var writer http.ResponseWriter = out
			if mode == "cancel_after_finish_write" {
				writer = &maas17CancelAtFinish{ResponseRecorder: out, cancel: cancel}
			}
			relay := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536}
			err := relay.Forward(ctx, writer, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: true})
			_, state, readErr := f.core.ReadRequest(context.Background(), in.RequestID)
			if readErr != nil { t.Fatal(readErr) }
			counter := readCounter(t, f, "tokens")
			t.Logf("mode=%s calls=%d forward_error=%v state=%s known=%s held=%s done=%v post_finish_visible=%v cancelled=%v", mode, calls, err, state, counter.Known, counter.Held, strings.Contains(out.Body.String(), "[DONE]"), strings.Contains(out.Body.String(), "AFTER_FINISH"), ctx.Err() != nil)
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
			if mode == "normal" {
				if err != nil || state != "succeeded" || counter.Known != "19" { t.Fatal("normal control failed") }
				return
			}
			if err == nil || state == "succeeded" || strings.Contains(out.Body.String(), "[DONE]") || counter.Known != "0" || counter.Held != "140" {
				t.Fatal("invalid/cancelled stream was reported and settled as successful")
			}
			if mode == "content_after_finish" && strings.Contains(out.Body.String(), "AFTER_FINISH") { t.Fatal("post-finish content escaped") }
		})
	}
}

type maas17CancelAtFinish struct {
	*httptest.ResponseRecorder
	cancel context.CancelFunc
}
func (w *maas17CancelAtFinish) WriteString(s string) (int, error) { return w.Write([]byte(s)) }
func (w *maas17CancelAtFinish) Write(b []byte) (int, error) {
	n, err := w.ResponseRecorder.Write(b)
	if strings.Contains(string(b), `"finish_reason":"stop"`) { w.cancel() }
	return n, err
}

func TestMAAS17PublisherOperationsGrant(t *testing.T) {
	f := setup(t, 1)
	ctx := context.Background()
	suffix := strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	role, user, password := "reviewrole_"+suffix, "reviewuser_"+suffix, uuid.NewString()
	for _, path := range []string{"../../config/mysql/release-permissions.sql", "../../config/mysql/kernel-permissions.sql"} {
		b, err := os.ReadFile(path)
		if err != nil { t.Fatal(err) }
		var clean []string
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(line), "--") { clean = append(clean, line) }
		}
		for _, q := range strings.Split(strings.Join(clean, "\n"), ";") {
			q = strings.TrimSpace(q)
			if !strings.Contains(q, "maas_release_publisher") { continue }
			q = strings.ReplaceAll(q, "maas_release_publisher", role)
			q = strings.ReplaceAll(q, "__MAAS_DATABASE__", "`"+f.config.DBName+"`")
			if _, err = f.db.Exec(q); err != nil { t.Fatal(err) }
		}
	}
	t.Cleanup(func() { _, _ = f.db.Exec("DROP ROLE "+role) })
	if _, err := f.db.Exec("CREATE USER '"+user+"'@'localhost' IDENTIFIED BY '"+password+"'"); err != nil { t.Fatal(err) }
	t.Cleanup(func() { _, _ = f.db.Exec("DROP USER '"+user+"'@'localhost'") })
	if _, err := f.db.Exec("GRANT "+role+" TO '"+user+"'@'localhost'"); err != nil { t.Fatal(err) }
	if _, err := f.db.Exec("SET DEFAULT ROLE "+role+" TO '"+user+"'@'localhost'"); err != nil { t.Fatal(err) }
	cfg := f.config.Clone()
	cfg.User, cfg.Passwd = user, password
	low, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil { t.Fatal(err) }
	defer low.Close()
	var currentRole string
	if err = low.QueryRow("SELECT CURRENT_ROLE()").Scan(&currentRole); err != nil || !strings.Contains(currentRole, role) { t.Fatal("default role", err) }
	_, permissionErr := low.Exec("SELECT operation_id FROM release_management_operations LIMIT 1")
	publisher, err := mysqlstore.New(low, "controlled-test", f.core)
	if err != nil { t.Fatal(err) }
	publisher = publisher.WithManagementOperations()
	st, err := publisher.Read(ctx, f.desired.CRUID)
	if err != nil { t.Fatal(err) }
	active := st.Active.PublicationID
	err = publisher.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "CloseAdmission", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Revision: st.Revision, EvidenceRefs: []string{}})
	after, readErr := f.gate.Read(ctx, f.desired.CRUID)
	if readErr != nil { t.Fatal(readErr) }
	t.Logf("original_role_default_active=true direct_operation_read=%v close_with_atomic_completion=%v admission_closed_after=%v", permissionErr, err, after.AdmissionClosed)
	if err != nil || !after.AdmissionClosed { t.Fatal("checked-in publisher grants cannot execute the opted-in management completion hook") }
}
