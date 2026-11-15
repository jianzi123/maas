package mysqlstore

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"net/url"
	"os"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
	"sigs.k8s.io/yaml"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func historyDesired(t *testing.T) release.Desired {
	t.Helper()
	b, e := os.ReadFile("../../../config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml")
	if e != nil {
		t.Fatal(e)
	}
	var m api.ModelRelease
	if yaml.Unmarshal(b, &m) != nil {
		t.Fatal("sample")
	}
	r := release.Resolution{Versions: map[string]string{"approved-registry": "1", "authorization_domain": "test-domain", "secretUID": "synthetic-uid", "secretRV": "1"}, GatewayNamespace: "higress", HostSuffix: "private.test", IngressClass: "higress", EndpointDNS: "approved.test", EndpointPort: 443, CredentialHandle: "never-export-handle", PluginDigest: "test-only"}
	return release.Desired{CRUID: uuid.NewString(), Namespace: m.Namespace, Name: m.Name, Alias: m.Spec.ModelAlias, Gateway: m.Spec.GatewayRef, Generation: 1, Revision: release.Revision(m.Spec, r), History: &release.HistoryCapture{Spec: m.Spec, Resolution: r, ResourceVersion: "1", AuthorizationDomain: "test-domain"}}
}

type historyLive struct {
	state history.LiveState
	err   error
}

func (l *historyLive) Current(context.Context, string, string) (history.LiveState, error) {
	return l.state, l.err
}

type historyEval struct {
	state   string
	reasons []string
}

func (e *historyEval) Evaluate(context.Context, string, string, history.LiveState) (history.Evaluation, error) {
	return history.Evaluation{State: e.state, Reasons: e.reasons}, nil
}
func historyReader(f *testDB, d release.Desired, l *historyLive) *history.Reader {
	return &history.Reader{DB: f.db, PayloadDB: f.db, CursorKey: []byte(strings.Repeat("k", 32)), Cluster: "test-cluster", Access: history.NamespaceAccess{Namespaces: map[string]bool{d.Namespace: true}, ScopeID: "controlled-admin", Domains: map[string]bool{"test-domain": true}}, Live: l, Evaluator: &historyEval{state: "eligible", reasons: []string{}}}
}
func TestMySQLRetainedHistory(t *testing.T) {
	ctx := context.Background()
	t.Run("capture_restart_immutable_and_ack", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, nil)
		d := historyDesired(t)
		connector, _ := mysql.NewConnector(f.config)
		drop := &atomic.Bool{}
		wrapped := sql.OpenDB(dropConnector{Connector: connector, drop: drop})
		defer wrapped.Close()
		fault := testStore(t, wrapped, nil)
		drop.Store(true)
		if _, e := fault.Observe(ctx, d); e != ErrCommitUnknown {
			t.Fatal(e)
		}
		st := observe(t, s, d)
		var created time.Time
		var originalRV string
		if e := f.db.QueryRow("SELECT created_at,source_resource_version FROM retained_release_snapshots").Scan(&created, &originalRV); e != nil {
			t.Fatal(e)
		}
		d.History.ResourceVersion = "2"
		again := observe(t, s, d)
		if again.Fence != st.Fence || again.Candidate.PublicationID != st.Candidate.PublicationID {
			t.Fatal("audit RV changed identity")
		}
		if count(t, f.db, "SELECT COUNT(*) FROM retained_release_snapshots") != 1 {
			t.Fatal("capture duplicate")
		}
		var after time.Time
		_ = f.db.QueryRow("SELECT created_at FROM retained_release_snapshots").Scan(&after)
		if !after.Equal(created) || originalRV != "1" {
			t.Fatal("capture timestamp changed")
		}
		live := &historyLive{state: history.LiveState{UID: d.CRUID, Version: "2", State: "present", SourceType: "ExternalAPI"}}
		r := historyReader(f, d, live)
		p, e := r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {d.CRUID}})
		if e != nil {
			t.Fatal(e)
		}
		b, _ := json.Marshal(p)
		if strings.Contains(string(b), "credential") || strings.Contains(string(b), "api-key") || strings.Contains(string(b), "approved.test") || strings.Contains(string(b), "never-export") {
			t.Fatal("secret/endpoint leaked", string(b))
		}
		row := p["data"].([]any)[0].(map[string]any)
		if row["rollback_eligibility"].(map[string]any)["state"] != "eligible" {
			t.Fatal(p)
		}
	})
	t.Run("legacy_hash_not_adopted", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, nil)
		d := historyDesired(t)
		capture := d.History
		d.History = nil
		observe(t, s, d)
		d.History = capture
		observe(t, s, d)
		r := historyReader(f, d, &historyLive{state: history.LiveState{State: "unknown"}})
		if _, e := r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {d.CRUID}}); e != history.ErrUnavailable {
			t.Fatal(e)
		}
		if count(t, f.db, "SELECT COUNT(*) FROM retained_release_snapshots") != 0 {
			t.Fatal("invented legacy spec/time")
		}
	})
	t.Run("uid_visibility_live_and_references", func(t *testing.T) {
		f := databaseFixture(t)
		d := historyDesired(t)
		observe(t, testStore(t, f.db, nil), d)
		live := &historyLive{state: history.LiveState{UID: d.CRUID, Version: "3", State: "present", SourceType: "ExternalAPI"}}
		r := historyReader(f, d, live)
		for _, state := range []string{"present", "deleting", "deleted", "replaced", "unknown"} {
			live.state.State = state
			if state == "replaced" {
				live.state.UID = uuid.NewString()
			}
			p, e := r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {d.CRUID}})
			if e != nil {
				t.Fatal(state, e)
			}
			row := p["data"].([]any)[0].(map[string]any)
			elig := row["rollback_eligibility"].(map[string]any)
			if state != "present" && elig["state"] == "eligible" {
				t.Fatal(state, p)
			}
		}
		r.Access = history.NamespaceAccess{}
		if _, e := r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {d.CRUID}}); e != history.ErrForbidden {
			t.Fatal(e)
		}
		r.Access = history.NamespaceAccess{Namespaces: map[string]bool{d.Namespace: true}, ScopeID: "admin", Domains: map[string]bool{"test-domain": true}}
		if _, e := r.ReadRevisions(ctx, d.Namespace, "other", url.Values{"cr_uid": {d.CRUID}}); e != history.ErrNotFound {
			t.Fatal(e)
		}
		live.state = history.LiveState{UID: d.CRUID, Version: "3", State: "present", SourceType: "ExternalAPI"}
		r.Evaluator = &historyEval{state: "blocked", reasons: []string{"reference_expired"}}
		p, e := r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {d.CRUID}})
		if e != nil || p["data"].([]any)[0].(map[string]any)["rollback_eligibility"].(map[string]any)["state"] != "blocked" {
			t.Fatal(p, e)
		}
		_, _ = f.db.Exec("UPDATE release_history_retention SET snapshot_state='pruning'")
		if _, e := r.LoadSpec(ctx, d.Namespace, d.Name, d.CRUID, d.Revision); e != history.ErrUnavailable {
			t.Fatal("pruned rollback", e)
		}
	})
	t.Run("pagination_ties_scope_and_new_insert", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, nil)
		d := historyDesired(t)
		uid := d.CRUID
		for i := 0; i < 3; i++ {
			d.Generation++
			d.History.Resolution.Versions["approval"] = string(rune('a' + i))
			d.Revision = release.Revision(d.History.Spec, d.History.Resolution)
			observe(t, s, d)
		}
		_, _ = f.db.Exec("UPDATE retained_release_snapshots SET created_at='2026-11-05 00:00:00.123456'")
		r := historyReader(f, d, &historyLive{state: history.LiveState{State: "unknown"}})
		q := url.Values{"cr_uid": {uid}, "page_size": {"1"}}
		page, e := r.ReadRevisions(ctx, d.Namespace, d.Name, q)
		if e != nil {
			t.Fatal(e)
		}
		seen := map[string]bool{}
		for i := 0; i < 3; i++ {
			row := page["data"].([]any)[0].(map[string]any)
			rev := row["revision"].(string)
			if seen[rev] {
				t.Fatal("duplicate page")
			}
			seen[rev] = true
			cursor, ok := page["next_cursor"].(string)
			if !ok {
				break
			}
			q.Set("cursor", cursor)
			if i == 0 {
				tampered := cursor[:len(cursor)-1] + "A"
				if tampered == cursor {
					tampered = cursor[:len(cursor)-1] + "B"
				}
				if _, err := r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {uid}, "page_size": {"1"}, "cursor": {tampered}}); err != history.ErrInvalid {
					t.Fatal("cursor integrity", err)
				}
				d.Generation++
				d.History.Resolution.Versions["approval"] = "late"
				d.Revision = release.Revision(d.History.Spec, d.History.Resolution)
				observe(t, s, d)
				_, _ = f.db.Exec("UPDATE retained_release_snapshots SET created_at='2000-01-01 00:00:00' WHERE revision=?", d.Revision)
				wrong := url.Values{"cr_uid": {uuid.NewString()}, "cursor": {cursor}}
				if _, e = r.ReadRevisions(ctx, d.Namespace, d.Name, wrong); e != history.ErrInvalid {
					t.Fatal("UID cursor", e)
				}
			}
			page, e = r.ReadRevisions(ctx, d.Namespace, d.Name, q)
			if e != nil {
				t.Fatal(e)
			}
		}
		if len(seen) != 3 {
			t.Fatal(seen)
		}
	})
	t.Run("rollback_CAS_UID_and_commit_unknown", func(t *testing.T) {
		f := databaseFixture(t)
		d := historyDesired(t)
		observe(t, testStore(t, f.db, nil), d)
		scheme := runtime.NewScheme()
		_ = api.AddToScheme(scheme)
		m := &api.ModelRelease{ObjectMeta: metav1.ObjectMeta{Namespace: d.Namespace, Name: d.Name, UID: types.UID(d.CRUID), ResourceVersion: "1", Generation: 2}, Spec: d.History.Spec}
		m.Spec.Lifecycle.RetainedRevisions = 3
		c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(m).Build()
		r := historyReader(f, d, nil)
		r.Live = history.KubeLive{Reader: c}
		service := history.RollbackService{History: r, Reader: c, Client: c}
		if _, e := service.Rollback(ctx, d.Namespace, d.Name, uuid.NewString(), d.Revision, "1"); e != history.ErrConflict {
			t.Fatal(e)
		}
		if _, e := service.Rollback(ctx, d.Namespace, d.Name, d.CRUID, d.Revision, "stale"); e != history.ErrConflict {
			t.Fatal(e)
		}
		lost := fake.NewClientBuilder().WithScheme(scheme).WithObjects(m.DeepCopy()).WithInterceptorFuncs(interceptor.Funcs{Update: func(ctx context.Context, c client.WithWatch, o client.Object, opts ...client.UpdateOption) error {
			if e := c.Update(ctx, o, opts...); e != nil {
				return e
			}
			return errors.New("test-only post-commit network error")
		}}).Build()
		service.Client = lost
		service.Reader = lost
		if _, e := service.Rollback(ctx, d.Namespace, d.Name, d.CRUID, d.Revision, "1"); e != history.ErrWriteOutcomeUnknown {
			t.Fatal("ACK unknown", e)
		}
		var got api.ModelRelease
		if lost.Get(ctx, client.ObjectKeyFromObject(m), &got) != nil || got.Spec.Lifecycle.RetainedRevisions != 2 {
			t.Fatal("write was not applied")
		}
		if _, e := service.Rollback(ctx, d.Namespace, d.Name, d.CRUID, d.Revision, "1"); e != history.ErrConflict {
			t.Fatal("old version replayed", e)
		}
	})
	t.Run("migration_v2_checksum_and_permission", func(t *testing.T) {
		f := databaseFixture(t)
		if _, e := f.db.Exec("UPDATE release_schema_migrations SET sha256=REPEAT('0',64) WHERE version=2"); e != nil {
			t.Fatal(e)
		}
		if e := Migrate(ctx, f.db); e != release.ErrConflict {
			t.Fatal(e)
		}
	})
}
