package kernel

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sigs.k8s.io/yaml"
	"strings"
	"testing"
	"time"
)

type boundaryWriter struct {
	*httptest.ResponseRecorder
	mode   string
	cancel context.CancelFunc
	wait   context.Context
}

func TestR1CommitRollbackBoundary(t *testing.T) {
	f := setup(t, 1)
	snap := mustAdmit(t, f, f.input(t))
	fin := finalFor(snap)
	fin.Result = "succeeded"
	fin.Submitted = true
	i, o, total, cached, reasoning := int64(12), int64(7), int64(19), int64(4), int64(3)
	fin.Usage = Usage{Input: &i, Output: &o, Total: &total, Cached: &cached, Reasoning: &reasoning, Source: "upstream"}
	original, cancel := context.WithCancel(context.Background())
	defer cancel()
	err := f.core.finalizeChecked(context.Background(), fin, func(tx *sql.Tx) error {
		var n int
		if e := tx.QueryRow("SELECT COUNT(*) FROM usage_events WHERE request_id=?", fin.RequestID).Scan(&n); e != nil || n != 1 {
			t.Fatal("precommit writes not exercised", e, n)
		}
		cancel()
		return original.Err()
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 0)
	if c := readCounter(t, f, "tokens"); c.Known != "0" || c.Reserved != "140" || c.Held != "0" {
		t.Fatal("partial accounting committed", c)
	}
	fin.Result = "cancelled"
	fin.Submitted = false
	fin.Usage = unavailableUsage("not_provided")
	if err = f.core.Finalize(context.Background(), fin); err != nil {
		t.Fatal(err)
	}
	if c := readCounter(t, f, "tokens"); c.Held != "140" || c.Known != "0" {
		t.Fatal(c)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
}

func (w *boundaryWriter) WriteString(s string) (int, error) { return w.Write([]byte(s)) }
func (w *boundaryWriter) Write(b []byte) (int, error) {
	n, e := w.ResponseRecorder.Write(b)
	if strings.Contains(string(b), `"finish_reason":"stop"`) && w.mode == "deadline_finish" {
		<-w.wait.Done()
	}
	if strings.Contains(string(b), `"usage":`) && w.mode == "cancel_committed" {
		w.cancel()
	}
	return n, e
}

func TestR1R2Boundaries(t *testing.T) {
	for _, mode := range []string{"deadline_finish", "cancel_committed", "independent_final", "contradictory_finish"} {
		t.Run(mode, func(t *testing.T) {
			f := setupUsagePolicy(t, 1, &UsagePolicy{"r1-r2-controlled", "final_only"})
			in := f.input(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "deadline_finish" {
				var done context.CancelFunc
				ctx, done = context.WithTimeout(ctx, 5*time.Second)
				defer done()
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if _, e := f.core.Admit(r.Context(), f.gate, in); e != nil {
					w.WriteHeader(503)
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"answer\"}}]}\n\n")
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n")
				if mode == "contradictory_finish" {
					io.WriteString(w, "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"length\"}]}\n\n")
				}
				io.WriteString(w, diagnosticFrame+"data: [DONE]\n\n")
			}))
			defer server.Close()
			w := &boundaryWriter{httptest.NewRecorder(), mode, cancel, ctx}
			r := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536}
			e := r.Forward(ctx, w, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: true})
			_, state, _ := f.core.ReadRequest(context.Background(), in.RequestID)
			c := readCounter(t, f, "tokens")
			if mode == "independent_final" {
				if e != nil || state != "succeeded" || c.Known != "19" {
					t.Fatal("approved final after finish rejected", e, state, c)
				}
			} else if mode == "cancel_committed" {
				if state != "succeeded" || c.Known != "19" || c.Held != "0" {
					t.Fatal("committed accounting reopened", state, c)
				}
			} else {
				if e == nil || state == "succeeded" || c.Known != "0" || c.Held != "140" || strings.Contains(w.Body.String(), "[DONE]") {
					t.Fatal("invalid success", e, state, c)
				}
				if money := readCounter(t, f, "money"); money.Known != "0" || money.Held != "520000" {
					t.Fatal("uncertain money changed", money)
				}
				var raw []byte
				if err := f.db.QueryRow("SELECT event_json FROM usage_events WHERE request_id=?", in.RequestID).Scan(&raw); err != nil {
					t.Fatal(err)
				}
				var event struct {
					Usage Usage `json:"usage"`
				}
				if json.Unmarshal(raw, &event) != nil || event.Usage.Input != nil || event.Usage.Output != nil || event.Usage.Total != nil {
					t.Fatal("failure actual fabricated")
				}
				assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='QUARANTINED' AND request_id=?", 1, in.RequestID)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		})
	}
}

func TestR3PublisherProjection(t *testing.T) {
	f := setup(t, 1)
	ctx := context.Background()
	suffix := strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	role, user := "r3role_"+suffix, "r3user_"+suffix
	for _, path := range []string{"../../config/mysql/release-permissions.sql", "../../config/mysql/kernel-permissions.sql"} {
		b, e := os.ReadFile(path)
		if e != nil {
			t.Fatal(e)
		}
		lines := []string{}
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(line), "--") {
				lines = append(lines, line)
			}
		}
		for _, q := range strings.Split(strings.Join(lines, "\n"), ";") {
			q = strings.TrimSpace(q)
			if !strings.Contains(q, "maas_release_publisher") {
				continue
			}
			q = strings.ReplaceAll(strings.ReplaceAll(q, "maas_release_publisher", role), "__MAAS_DATABASE__", "`"+f.config.DBName+"`")
			if _, e = f.db.Exec(q); e != nil {
				t.Fatal(e)
			}
		}
	}
	t.Cleanup(func() { f.db.Exec("DROP ROLE " + role) })
	if _, e := f.db.Exec("CREATE USER '" + user + "'@'localhost'"); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { f.db.Exec("DROP USER '" + user + "'@'localhost'") })
	for _, q := range []string{"GRANT " + role + " TO '" + user + "'@'localhost'", "SET DEFAULT ROLE " + role + " TO '" + user + "'@'localhost'"} {
		if _, e := f.db.Exec(q); e != nil {
			t.Fatal(e)
		}
	}
	cfg := f.config.Clone()
	cfg.User = user
	cfg.Passwd = ""
	low, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer low.Close()
	var current string
	if low.QueryRow("SELECT CURRENT_ROLE()").Scan(&current) != nil || !strings.Contains(current, role) {
		t.Fatal("default role absent")
	}
	pub, _ := mysqlstore.New(low, "controlled-test", f.core)
	pub = pub.WithManagementOperations()
	b, _ := os.ReadFile("../../config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml")
	var m api.ModelRelease
	if yaml.Unmarshal(b, &m) != nil {
		t.Fatal("sample")
	}
	m.Spec.ModelAlias = f.desired.Alias
	m.Spec.GatewayRef = api.Ref{Name: f.desired.Gateway.Name, Revision: "r3-approved"}
	m.Spec.Source.ExternalAPI.UpstreamModel = f.profile.UpstreamModel
	d := f.desired
	d.Gateway = m.Spec.GatewayRef
	d.Generation = 2
	res := release.Resolution{Versions: map[string]string{"authorization_domain": "r3-test"}}
	d.Revision = release.Revision(m.Spec, res)
	d.History = &release.HistoryCapture{Spec: m.Spec, Resolution: res, AuthorizationDomain: "r3-test", ResourceVersion: "2"}
	insert := func(action, desired string, gen int64) string {
		id := uuid.NewString()
		_, err := f.db.Exec(`INSERT INTO release_management_operations(cluster_id,operation_id,scope_id,namespace,name,action,desired_state,cr_uid,expected_rv,spec_sha256,state,acknowledged,requested_generation) VALUES('controlled-test',?,'r3',?,?,?,?,?,'2',?,'Running',TRUE,?)`, id, d.Namespace, d.Name, action, desired, d.CRUID, release.Hash(m.Spec), gen)
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	operation := insert("Update", "Published", 2)
	st, e := pub.Observe(ctx, d)
	if e != nil {
		t.Fatal("observe", e)
	}
	p := f.profile
	p.Binding = *st.Candidate
	if e = f.core.RegisterProfile(ctx, p); e != nil {
		t.Fatal(e)
	}
	st, _ = pub.Read(ctx, d.CRUID)
	active, target := st.Active.PublicationID, st.Candidate.PublicationID
	cmd := release.Command{ID: uuid.NewString(), Action: "Activate", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Target: &target, Revision: st.Revision, EvidenceRefs: st.EvidenceRefs}
	if e = pub.Apply(ctx, cmd); e != nil {
		t.Fatal("activate with hook", e)
	}
	var state string
	if f.db.QueryRow("SELECT state FROM release_management_operations WHERE operation_id=?", operation).Scan(&state) != nil || state != "Succeeded" {
		t.Fatal("activate completion", state)
	}
	for _, q := range []string{"UPDATE release_management_operations SET action='Delete'", "UPDATE release_management_operations SET spec_sha256=REPEAT('0',64)", "UPDATE release_management_operations SET expected_rv='bad'", "UPDATE platform_keys SET revoked=FALSE", "UPDATE budget_windows SET uncertainty_held=0", "DELETE FROM usage_events", "CREATE TABLE denied(id INT)"} {
		_, err := low.Exec(q)
		var denied *mysql.MySQLError
		if !errors.As(err, &denied) || (denied.Number != 1142 && denied.Number != 1143) {
			t.Fatal("expected permission denial", q, err)
		}
		t.Log("denied", q, "mysql", denied.Number)
	}
	st, _ = pub.Read(ctx, d.CRUID)
	active = st.Active.PublicationID
	closeCmd := release.Command{ID: uuid.NewString(), Action: "CloseAdmission", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Revision: st.Revision, EvidenceRefs: []string{}}
	if _, e = f.db.Exec("REVOKE UPDATE(state) ON `" + f.config.DBName + "`.release_management_operations FROM " + role); e != nil {
		t.Fatal(e)
	}
	if e = pub.Apply(ctx, closeCmd); e == nil {
		t.Fatal("completion failure ignored")
	}
	after, _ := f.gate.Read(ctx, d.CRUID)
	if after.AdmissionClosed {
		t.Fatal("partial close committed")
	}
	f.db.Exec("GRANT UPDATE(state) ON `" + f.config.DBName + "`.release_management_operations TO " + role)
	connector, _ := mysql.NewConnector(cfg)
	ack := &ackConnector{Connector: connector}
	faultDB := sql.OpenDB(ack)
	defer faultDB.Close()
	fault, _ := mysqlstore.New(faultDB, "controlled-test", f.core)
	fault = fault.WithManagementOperations()
	ack.lose.Store(true)
	if e = fault.Apply(ctx, closeCmd); !errors.Is(e, mysqlstore.ErrCommitUnknown) {
		t.Fatal("ACK loss", e)
	}
	if e = pub.Apply(ctx, closeCmd); e != nil {
		t.Fatal("same command recovery", e)
	}
	d.Generation = 3
	d.Paused = true
	d.History = nil
	m.Spec.Lifecycle.DesiredState = "Paused"
	pauseOp := insert("Pause", "Paused", 3)
	if _, e = pub.Observe(ctx, d); e != nil {
		t.Fatal(e)
	}
	st, _ = pub.Read(ctx, d.CRUID)
	active = st.Active.PublicationID
	if e = pub.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "RecordCleanup", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Revision: st.Revision, EvidenceRefs: []string{}}); e != nil {
		t.Fatal("cleanup", e)
	}
	if f.db.QueryRow("SELECT state FROM release_management_operations WHERE operation_id=?", pauseOp).Scan(&state) != nil || state != "Succeeded" {
		t.Fatal("pause completion", state)
	}
}
