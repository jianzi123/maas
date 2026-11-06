//go:build envtest

package integration

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
	"github.com/jianzi123/maas/internal/release/management"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	"sigs.k8s.io/yaml"
)

// Real local API-server/etcd + MySQL + TCP HTTP. Only metadata resolution and
// gateway producer are test adapters. Nothing here calls a model or starts Pods.
func TestManagementHTTPLifecycle(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") || os.Getenv("KUBEBUILDER_ASSETS") == "" {
		t.Fatal("explicit disposable MySQL and envtest assets required")
	}
	ctx := context.Background()
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = 3 * time.Second
	admin, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer admin.Close()
	database := "maas_operations_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.Exec("CREATE DATABASE `" + database + "`"); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP DATABASE `" + database + "`")
	cfg.DBName = database
	db, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	if e = kernel.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	if e = mysqlstore.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	core, e := kernel.New(db, "management-envtest", []byte(strings.Repeat("p", 32)), nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	if e = core.Configure(ctx, kernel.RatePolicy{Revision: "test-only", Epoch: 1, WindowMS: 1000, GlobalLimit: 100, KeyLimit: 100}, 2); e != nil {
		t.Fatal(e)
	}
	publisher, e := mysqlstore.New(db, "management-envtest", core)
	if e != nil {
		t.Fatal(e)
	}
	publisher = publisher.WithManagementOperations()
	existing := false
	environment := &envtest.Environment{UseExistingCluster: &existing, CRDDirectoryPaths: []string{filepath.Join("..", "..", "config", "crd")}, ErrorIfCRDPathMissing: true}
	kubeConfig, e := environment.Start()
	if e != nil {
		t.Fatal(e)
	}
	defer func() {
		if e := environment.Stop(); e != nil {
			t.Error(e)
		}
	}()
	scheme := runtime.NewScheme()
	_ = api.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	kube, e := client.New(kubeConfig, client.Options{Scheme: scheme})
	if e != nil {
		t.Fatal(e)
	}
	ns := "maas-models-example"
	if e = kube.Create(ctx, &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: ns}}); e != nil {
		t.Fatal(e)
	}
	access := history.NamespaceAccess{Namespaces: map[string]bool{ns: true}, Domains: map[string]bool{"test-domain": true}, ScopeID: "test-session"}
	b, e := os.ReadFile("../../config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml")
	if e != nil {
		t.Fatal(e)
	}
	original := new(api.ModelRelease)
	if e = yaml.Unmarshal(b, original); e != nil {
		t.Fatal(e)
	}
	original.Name = "managed-model"
	resolution := release.Resolution{Versions: map[string]string{"authorization_domain": "test-domain"}, GatewayNamespace: ns, IngressClass: "higress", HostSuffix: "test.invalid", EndpointDNS: "fixture.invalid", EndpointPort: 443, CredentialHandle: "opaque-test-only", PluginDigest: strings.Repeat("1", 64)}
	updated := original.DeepCopy()
	updated.Spec.Source.ExternalAPI.UpstreamModel = "test-second-model"
	registry := &management.Registry{Access: access, Entries: []management.RegistryEntry{{Namespace: ns, Spec: original.Spec, Resolution: resolution}, {Namespace: ns, Spec: updated.Spec, Resolution: resolution}}}
	hr := &history.Reader{DB: db, PayloadDB: db, Cluster: "management-envtest", Access: access, CursorKey: []byte(strings.Repeat("c", 32)), Live: history.KubeLive{Reader: kube}}
	hr.Evaluator = history.ResolverEvaluator{Resolver: registry, Loader: hr}
	op := &management.Operations{DB: db, Cluster: "management-envtest", Access: access}
	mutation := &ackLossClient{Client: kube}
	service := &management.Service{Client: mutation, Reader: kube, Operations: op, History: hr, Resolver: registry, Access: access, CursorKey: hr.CursorKey}
	session, csrf := uuid.NewString()+uuid.NewString(), uuid.NewString()+uuid.NewString()
	digest := func(s string) string { v := sha256.Sum256([]byte(s)); return hex.EncodeToString(v[:]) }
	handler := controlapi.Handler{Core: core, Sessions: controlapi.BootstrapSession{SessionSHA256: digest(session), CSRFSHA256: digest(csrf), Origin: "http://127.0.0.1", Expires: time.Now().Add(10 * time.Minute)}, Releases: service, Revisions: hr, Models: core, ModelGate: publisher, ModelNamespaces: access.Namespaces}
	server := httptest.NewServer(handler)
	extraDBs := []*sql.DB{}
	defer func() {
		server.Close()
		for _, d := range extraDBs {
			d.Close()
		}
	}()
	evidence := []map[string]any{}
	call := func(method, path, rv string, body any, want int, schema string) map[string]any {
		t.Helper()
		var payload []byte
		if body != nil {
			payload, e = json.Marshal(body)
			if e != nil {
				t.Fatal(e)
			}
		}
		r, _ := http.NewRequest(method, server.URL+path, bytes.NewReader(payload))
		r.AddCookie(&http.Cookie{Name: "maas_session", Value: session})
		r.Header.Set("Origin", "http://127.0.0.1")
		r.Header.Set("X-CSRF-Token", csrf)
		if body != nil {
			r.Header.Set("Content-Type", "application/json")
		}
		if rv != "" {
			r.Header.Set("If-Match", `"`+rv+`"`)
		}
		response, err := server.Client().Do(r)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		raw, err := io.ReadAll(response.Body)
		if err != nil {
			t.Fatal(err)
		}
		var out map[string]any
		if json.Unmarshal(raw, &out) != nil {
			t.Fatalf("invalid response %d", response.StatusCode)
		}
		if response.StatusCode != want {
			t.Fatalf("%s %s: %d want %d: %s", method, path, response.StatusCode, want, raw)
		}
		if schema != "" && protocol.Validate(schema, out) != nil {
			t.Fatalf("strict %s: %s", schema, raw)
		}
		if response.Header.Get("X-Request-ID") == "" {
			t.Fatal("missing trusted HTTP ID")
		}
		evidence = append(evidence, map[string]any{"method": method, "path": path, "http_status": want, "body": out, "etag": response.Header.Get("ETag")})
		return out
	}
	input := func(m *api.ModelRelease) map[string]any {
		return map[string]any{"apiVersion": api.GroupVersion.String(), "kind": "ModelRelease", "metadata": map[string]any{"namespace": m.Namespace, "name": m.Name}, "spec": m.Spec}
	}
	collection := "/api/admin/v1/model-releases"
	path := collection + "/" + ns + "/" + original.Name
	operationPath := func(out map[string]any) string {
		return "/api/admin/v1/release-operations/" + out["operation"].(map[string]any)["id"].(string)
	}
	live := func() *api.ModelRelease {
		m := new(api.ModelRelease)
		if e := kube.Get(ctx, client.ObjectKeyFromObject(original), m); e != nil {
			t.Fatal(e)
		}
		return m
	}
	reconciler := &release.Reconciler{Client: kube, Reader: kube, Dependencies: release.Dependencies{Control: publisher, Inventory: publisher, Resolver: registry, Bundle: noGatewayBundle{}, Plugin: noGatewayProducer{}}}
	reconcile := func() {
		t.Helper()
		if _, e := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKeyFromObject(original)}); e != nil {
			t.Fatal(e)
		}
	}
	var createOp, pauseOp, deleteOp, unknownOp, pausedCreateOp string
	var revision string
	t.Run("create-list-detail-and-exact-operation", func(t *testing.T) {
		result := call("POST", collection, "", input(original), 202, "ReleaseAccepted")
		createOp = operationPath(result)
		if result["operation"].(map[string]any)["state"] != "Running" {
			t.Fatal(result)
		}
		got := call("GET", path, "", nil, 200, "ReleaseModelRelease")
		if _, ok := got["status"]; ok {
			t.Fatal("unobserved status fabricated")
		}
		page := call("GET", collection+"?page_size=1", "", nil, 200, "ReleaseList")
		if len(page["data"].([]any)) != 1 {
			t.Fatal(page)
		}
		call("GET", createOp, "", nil, 200, "ReleaseOperation")
		reconcile()
		m := live()
		if m.Status.Phase == "Ready" {
			t.Fatal("fixture became ready")
		}
		page = call("GET", path+"/revisions?cr_uid="+string(m.UID), "", nil, 200, "ReleaseRevisionPage")
		revision = page["data"].([]any)[0].(map[string]any)["revision"].(string)
		if call("GET", createOp, "", nil, 200, "ReleaseOperation")["state"] != "Running" {
			t.Fatal("202 promoted to published")
		}
	})
	t.Run("catalogue-from-same-immutable-kernel-profile", func(t *testing.T) {
		m := live()
		state, err := publisher.Read(ctx, string(m.UID))
		if err != nil || state.Candidate == nil {
			t.Fatal(err)
		}
		profile := kernel.Profile{CRUID: string(m.UID), Namespace: ns, Name: m.Name, Alias: m.Spec.ModelAlias, Binding: *state.Candidate, SourceID: uuid.NewString(), SourceType: "external", UpstreamModel: m.Spec.Source.ExternalAPI.UpstreamModel, ConfigRevision: "test-config", CapabilityRevision: "test-capability", RouteDigest: strings.Repeat("2", 64), GatewayEpoch: 1, ApprovalRef: "test-only-metadata", Catalog: &kernel.CatalogMetadata{DisplayName: "Controlled model", Capabilities: map[string]any{"streaming": true, "verified_max_output_tokens": 100, "temperature_supported": false, "usage_available": "unknown", "capability_revision": "test-capability", "hard_budget_status": "unverified", "budget_unavailable_reason": "No real gateway proof", "protocols": []any{"chat_completions"}}}}
		if err = core.RegisterProfile(ctx, profile); err != nil {
			t.Fatal(err)
		}
		result := call("GET", "/api/admin/v1/models", "", nil, 200, "AdminModelList")
		data := result["data"].([]any)
		if len(data) != 1 || data[0].(map[string]any)["callable"] != false {
			t.Fatal("catalogue bypassed proof gate", result)
		}
	})
	t.Run("namespace-bound-pagination-and-invalid-cursors", func(t *testing.T) {
		m := original.DeepCopy()
		m.Name = "zz-second-model"
		m.Spec.ModelAlias = "controlled-paused"
		m.Spec.Lifecycle.DesiredState = "Paused"
		accepted := call("POST", collection, "", input(m), 202, "ReleaseAccepted")
		pausedCreateOp = operationPath(accepted)
		if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKeyFromObject(m)}); err != nil {
			t.Fatal(err)
		}
		if call("GET", operationPath(accepted), "", nil, 200, "ReleaseOperation")["state"] != "Succeeded" {
			t.Fatal("paused Create did not complete")
		}
		first := call("GET", collection+"?page_size=1", "", nil, 200, "ReleaseList")
		cursor, ok := first["next_cursor"].(string)
		if !ok || cursor == "" {
			t.Fatal("missing continuation", first)
		}
		second := call("GET", collection+"?page_size=1&cursor="+url.QueryEscape(cursor), "", nil, 200, "ReleaseList")
		if first["data"].([]any)[0].(map[string]any)["metadata"].(map[string]any)["name"] == second["data"].([]any)[0].(map[string]any)["metadata"].(map[string]any)["name"] {
			t.Fatal("page repeated")
		}
		call("GET", collection+"?page_size=2&cursor="+url.QueryEscape(cursor), "", nil, 400, "Error")
		call("GET", collection+"?page_size=1&namespace="+ns+"&cursor="+url.QueryEscape(cursor), "", nil, 400, "Error")
	})
	t.Run("stale-version-and-uid-conflicts", func(t *testing.T) {
		m := live()
		call("PUT", path, "stale", input(m), 409, "Error")
		call("POST", path+"/rollback", m.ResourceVersion, map[string]any{"target_revision": revision, "expected_cr_uid": uuid.NewString()}, 409, "Error")
		call("PUT", path, "", input(m), 400, "Error")
	})
	t.Run("unapproved-reference-and-unknown-fields-rejected", func(t *testing.T) {
		m := live()
		m.Spec.Source.ExternalAPI.EndpointRef.Revision = "not-approved"
		before := mutation.writes
		call("PUT", path, m.ResourceVersion, input(m), 503, "Error")
		bad := input(m)
		bad["status"] = map[string]any{"phase": "Ready"}
		call("PUT", path, m.ResourceVersion, bad, 400, "Error")
		if mutation.writes != before {
			t.Fatal("unapproved or unvalidated mutation")
		}
	})
	t.Run("api-server-CAS-race-is-not-retried", func(t *testing.T) {
		m := live()
		before := mutation.writes
		mutation.conflictNext = true
		call("PUT", path, m.ResourceVersion, input(m), 409, "Error")
		if mutation.writes != before+1 {
			t.Fatal("CAS retried")
		}
		reconcile()
	})
	t.Run("pause-during-registry-outage", func(t *testing.T) {
		m := live()
		m.Spec.Lifecycle.DesiredState = "Paused"
		service.Resolver = nil
		out := call("PUT", path, m.ResourceVersion, input(m), 202, "ReleaseAccepted")
		pauseOp = operationPath(out)
		service.Resolver = registry
		if out["operation"].(map[string]any)["action"] != "Pause" {
			t.Fatal(out)
		}
		reconcile()
		if call("GET", pauseOp, "", nil, 200, "ReleaseOperation")["state"] != "Succeeded" {
			t.Fatal("pause completion missing")
		}
	})
	t.Run("resume-and-update", func(t *testing.T) {
		m := live()
		m.Spec.Lifecycle.DesiredState = "Published"
		out := call("PUT", path, m.ResourceVersion, input(m), 202, "ReleaseAccepted")
		if out["operation"].(map[string]any)["action"] != "Resume" {
			t.Fatal(out)
		}
		reconcile()
		m = live()
		m.Spec.Source.ExternalAPI.UpstreamModel = updated.Spec.Source.ExternalAPI.UpstreamModel
		call("PUT", path, m.ResourceVersion, input(m), 202, "ReleaseAccepted")
		reconcile()
	})
	t.Run("rollback-reuses-retained-source", func(t *testing.T) {
		m := live()
		call("POST", path+"/rollback", m.ResourceVersion, map[string]any{"target_revision": revision, "expected_cr_uid": string(m.UID)}, 202, "ReleaseAccepted")
		if live().Spec.Source.ExternalAPI.UpstreamModel != original.Spec.Source.ExternalAPI.UpstreamModel {
			t.Fatal("wrong rollback spec")
		}
		reconcile()
	})
	t.Run("lost-ack-query-never-replays", func(t *testing.T) {
		m := live()
		m.Spec.Lifecycle.ProgressDeadlineSeconds++
		mutation.loseNext = true
		out := call("PUT", path, m.ResourceVersion, input(m), 202, "ReleaseAccepted")
		unknownOp = operationPath(out)
		count := mutation.writes
		if out["resource"] != nil || out["operation"].(map[string]any)["state"] != "Unknown" {
			t.Fatal(out)
		}
		reconcile()
		for i := 0; i < 3; i++ {
			if call("GET", unknownOp, "", nil, 200, "ReleaseOperation")["state"] != "Unknown" {
				t.Fatal("inferred lost write from current CR")
			}
		}
		if mutation.writes != count {
			t.Fatal("operation GET replayed mutation")
		}
		// Recreate the HTTP/core/operation adapters with a new primary connection.
		// No in-memory operation identity or write result is carried across.
		server.Close()
		restartedDB, err := sql.Open("mysql", cfg.FormatDSN())
		if err != nil {
			t.Fatal(err)
		}
		extraDBs = append(extraDBs, restartedDB)
		restartedCore, err := kernel.New(restartedDB, "management-envtest", []byte(strings.Repeat("p", 32)), nil, nil)
		if err != nil {
			t.Fatal(err)
		}
		service.Operations = &management.Operations{DB: restartedDB, Cluster: op.Cluster, Access: access}
		handler.Core = restartedCore
		server = httptest.NewServer(handler)
		if call("GET", unknownOp, "", nil, 200, "ReleaseOperation")["state"] != "Unknown" || mutation.writes != count {
			t.Fatal("restart lost unknown boundary")
		}
	})
	t.Run("delete-and-query-after-removal", func(t *testing.T) {
		m := live()
		out := call("DELETE", path, m.ResourceVersion, nil, 202, "ReleaseAccepted")
		deleteOp = operationPath(out)
		reconcile()
		if err := kube.Get(ctx, client.ObjectKeyFromObject(original), new(api.ModelRelease)); !apierrors.IsNotFound(err) {
			t.Fatalf("CR not removed: %v", err)
		}
		if call("GET", deleteOp, "", nil, 200, "ReleaseOperation")["state"] != "Succeeded" {
			t.Fatal("delete outcome not retained")
		}
		call("GET", path, "", nil, 404, "Error")
		if call("GET", unknownOp, "", nil, 200, "ReleaseOperation")["state"] != "Unknown" {
			t.Fatal("unknown rewritten by later deletion")
		}
	})
	t.Run("scope-and-query-validation", func(t *testing.T) {
		call("GET", collection+"?namespace=other", "", nil, 403, "Error")
		call("GET", createOp+"?request_id="+uuid.NewString(), "", nil, 400, "Error")
		call("GET", "/api/admin/v1/release-operations/"+uuid.NewString(), "", nil, 404, "Error")
		call("GET", collection+"?page_size=0", "", nil, 400, "Error")
	})
	t.Run("write-authentication-and-csrf-before-mutation", func(t *testing.T) {
		before := mutation.writes
		for _, mode := range []string{"missing-session", "missing-csrf", "platform-key"} {
			r, _ := http.NewRequest("DELETE", server.URL+path, nil)
			r.Header.Set("Origin", "http://127.0.0.1")
			if mode != "missing-session" {
				r.AddCookie(&http.Cookie{Name: "maas_session", Value: session})
			}
			if mode == "platform-key" {
				r.Header.Set("Authorization", "Bearer invalid-test-only")
				r.Header.Set("X-CSRF-Token", csrf)
			}
			response, err := server.Client().Do(r)
			if err != nil {
				t.Fatal(err)
			}
			response.Body.Close()
			if response.StatusCode != 401 && response.StatusCode != 403 {
				t.Fatal(mode, response.StatusCode)
			}
		}
		if mutation.writes != before {
			t.Fatal("unauthorized mutation")
		}
	})
	t.Run("operation-reader-privilege-boundary", func(t *testing.T) {
		account := "op_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
		if _, err := admin.Exec("CREATE USER '" + account + "'@'localhost'"); err != nil {
			t.Fatal(err)
		}
		defer admin.Exec("DROP USER '" + account + "'@'localhost'")
		grants := []string{
			"GRANT SELECT, UPDATE(state,reason,publication_id,updated_at) ON `" + database + "`.release_management_operations TO '" + account + "'@'localhost'",
			"GRANT SELECT(cluster_id,cr_uid,namespace,name,last_observed_generation,active_id,desired_mode,admission_closed,cleanup_complete,tombstone) ON `" + database + "`.release_links TO '" + account + "'@'localhost'",
			"GRANT SELECT(cluster_id,publication_id,revision,generation,state,activated) ON `" + database + "`.publications TO '" + account + "'@'localhost'",
			"GRANT SELECT(cluster_id,cr_uid,revision,spec_sha256) ON `" + database + "`.retained_release_snapshots TO '" + account + "'@'localhost'",
		}
		for _, grant := range grants {
			if _, err := admin.Exec(grant); err != nil {
				t.Fatal(err)
			}
		}
		narrowCfg := *cfg
		narrowCfg.User = account
		narrow, err := sql.Open("mysql", narrowCfg.FormatDSN())
		if err != nil {
			t.Fatal(err)
		}
		defer narrow.Close()
		reader := management.Operations{DB: narrow, Cluster: op.Cluster, Access: access}
		if _, err = reader.Read(ctx, strings.TrimPrefix(createOp, "/api/admin/v1/release-operations/")); err != nil {
			t.Fatal(err)
		}
		id := strings.TrimPrefix(pausedCreateOp, "/api/admin/v1/release-operations/")
		if _, err = db.Exec("UPDATE release_management_operations SET state='Running' WHERE cluster_id=? AND operation_id=?", op.Cluster, id); err != nil {
			t.Fatal(err)
		}
		projected, err := reader.Read(ctx, id)
		if err != nil || projected["state"] != "Succeeded" {
			t.Fatal("narrow completion projection", err, projected)
		}
		for _, query := range []string{"SELECT spec_bytes FROM retained_release_snapshots", "UPDATE release_links SET admission_closed=FALSE", "DELETE FROM usage_events", "SELECT * FROM budget_windows"} {
			rows, err := narrow.Query(query)
			if rows != nil {
				rows.Close()
			}
			if err == nil {
				t.Fatal("unexpected permission", query)
			}
		}
	})
	t.Run("administration-never-generates-or-settles", func(t *testing.T) {
		for _, table := range []string{"generation_requests", "usage_events", "budget_windows"} {
			var n int
			if e := db.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&n); e != nil || n != 0 {
				t.Fatalf("unexpected business write %s count=%d err=%v", table, n, e)
			}
		}
	})
	if output := os.Getenv("MAAS_MANAGEMENT_HTTP_EVIDENCE"); output != "" {
		b, _ := json.MarshalIndent(evidence, "", "  ")
		if e = os.WriteFile(output, b, 0600); e != nil {
			t.Fatal(e)
		}
	}
}

type ackLossClient struct {
	client.Client
	loseNext     bool
	conflictNext bool
	writes       int
}

func (c *ackLossClient) Update(ctx context.Context, obj client.Object, opts ...client.UpdateOption) error {
	c.writes++
	if c.conflictNext {
		c.conflictNext = false
		other := new(api.ModelRelease)
		if e := c.Client.Get(ctx, client.ObjectKeyFromObject(obj), other); e != nil {
			return e
		}
		other.Spec.Lifecycle.ProgressDeadlineSeconds++
		if e := c.Client.Update(ctx, other); e != nil {
			return e
		}
	}
	e := c.Client.Update(ctx, obj, opts...)
	if e == nil && c.loseNext {
		c.loseNext = false
		return errors.New("injected ACK loss after original API-server update")
	}
	return e
}
func (c *ackLossClient) Create(ctx context.Context, obj client.Object, opts ...client.CreateOption) error {
	c.writes++
	return c.Client.Create(ctx, obj, opts...)
}
func (c *ackLossClient) Delete(ctx context.Context, obj client.Object, opts ...client.DeleteOption) error {
	c.writes++
	return c.Client.Delete(ctx, obj, opts...)
}

type noGatewayProducer struct{}

func (noGatewayProducer) Compile(context.Context, *api.ModelRelease, release.Resolution, release.Binding, string) (*unstructured.Unstructured, error) {
	return nil, release.ErrDependencyMissing
}

type noGatewayBundle struct{}

func (noGatewayBundle) Ensure(context.Context, string, release.Binding, release.RegistryEntry) error {
	return release.ErrDependencyMissing
}
func (noGatewayBundle) Remove(context.Context, string, string) error { return nil }
