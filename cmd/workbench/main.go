//go:build localworkbench

// Local workbench uses private disposable MySQL and a dedicated API-server.
package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
	"github.com/jianzi123/maas/internal/release/management"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"github.com/jianzi123/maas/internal/workbench"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	"sigs.k8s.io/yaml"
	"strings"
	"syscall"
	"time"
)

type unavailableGateway struct{}

func (unavailableGateway) Compile(context.Context, *api.ModelRelease, release.Resolution, release.Binding, string) (*unstructured.Unstructured, error) {
	return nil, release.ErrDependencyMissing
}

type localBundle struct{}

func (localBundle) Ensure(context.Context, string, release.Binding, release.RegistryEntry) error {
	return release.ErrDependencyMissing
}
func (localBundle) Remove(context.Context, string, string) error { return nil }

// The local approval contains only the bundled inert example references. Alias
// choice is allowed for managing multiple CRs; it never enables inference.
type localMetadataRegistry struct{ management.Registry }

func (r localMetadataRegistry) Resolve(ctx context.Context, m *api.ModelRelease) (release.Resolution, error) {
	copy := m.DeepCopy()
	copy.Spec.ModelAlias = "local-example"
	return r.Registry.Resolve(ctx, copy)
}

func run() (runErr error) {
	address := flag.String("listen", "127.0.0.1:4179", "loopback HTTP address")
	root := flag.String("root", ".", "repository root")
	flag.Parse()
	host, _, e := net.SplitHostPort(*address)
	if e != nil || host != "127.0.0.1" {
		return errors.New("explicit loopback address required")
	}
	socket := os.Getenv("MAAS_WORKBENCH_MYSQL_SOCKET")
	if !strings.HasPrefix(socket, "/tmp/maas-workbench.") || filepath.Base(socket) != "mysql.sock" || os.Getenv("KUBEBUILDER_ASSETS") == "" {
		return errors.New("owned disposable MySQL socket and envtest assets required")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	go func() {
		scan := bufio.NewScanner(os.Stdin)
		for scan.Scan() {
			if scan.Text() == "stop" {
				cancel()
				return
			}
		}
		cancel()
	}()
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = 3 * time.Second
	admin, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		return errors.New("local database unavailable")
	}
	defer admin.Close()
	if _, e = admin.ExecContext(ctx, "CREATE DATABASE maas_workbench"); e != nil {
		return errors.New("disposable database initialization failed")
	}
	cfg.DBName = "maas_workbench"
	db, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		return errors.New("local database unavailable")
	}
	defer db.Close()
	if e = kernel.Migrate(ctx, db); e != nil {
		return e
	}
	if e = mysqlstore.Migrate(ctx, db); e != nil {
		return e
	}
	pepper, cursor := make([]byte, 32), make([]byte, 32)
	if _, e = rand.Read(pepper); e != nil {
		return e
	}
	if _, e = rand.Read(cursor); e != nil {
		return e
	}
	core, e := kernel.New(db, "local-workbench", pepper, nil, nil)
	if e != nil {
		return e
	}
	if e = core.Configure(ctx, kernel.RatePolicy{Revision: "local-disabled-inference", Epoch: 1, WindowMS: 1000, GlobalLimit: 1, KeyLimit: 1}, 1); e != nil {
		return e
	}
	connections, e := installLocalConnections(ctx, db, cfg, *root)
	if e != nil {
		return e
	}
	defer connections.Close()
	core, e = kernel.New(connections.Core, "local-workbench", pepper, nil, nil)
	if e != nil {
		return e
	}
	publisherRuntime, e := mysqlstore.OpenPublisher(ctx, connections.PublisherDSN, "local-workbench", core)
	if e != nil {
		return e
	}
	defer publisherRuntime.Close()
	publisher := publisherRuntime.Store
	useExisting := false
	environment := &envtest.Environment{UseExistingCluster: &useExisting, CRDDirectoryPaths: []string{filepath.Join(*root, "config", "crd")}, ErrorIfCRDPathMissing: true}
	defer func() {
		if err := environment.Stop(); err != nil && runErr == nil {
			runErr = errors.New("temporary API-server cleanup failed")
		}
	}()
	kubeConfig, e := environment.Start()
	if e != nil {
		return errors.New("temporary API-server failed to start")
	}
	if ctx.Err() != nil {
		return nil
	}
	scheme := runtime.NewScheme()
	_ = api.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	kube, e := client.New(kubeConfig, client.Options{Scheme: scheme})
	if e != nil {
		return e
	}
	ns := "maas-local"
	if e = kube.Create(ctx, &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: ns}}); e != nil {
		return e
	}
	b, e := os.ReadFile(filepath.Join(*root, "config", "samples", "MAAS-2-modelrelease-externalapi-v0.4.example.yaml"))
	if e != nil {
		return e
	}
	example := new(api.ModelRelease)
	if e = yaml.Unmarshal(b, example); e != nil {
		return e
	}
	example.Namespace = ns
	example.Name = "local-example"
	example.Spec.ModelAlias = "local-example"
	example.Spec.Source.ExternalAPI.UpstreamModel = "local-example-v1"
	second := example.DeepCopy()
	second.Spec.Source.ExternalAPI.UpstreamModel = "local-example-v2"
	access := history.NamespaceAccess{Namespaces: map[string]bool{ns: true}, Domains: map[string]bool{"local-workbench": true}, ScopeID: "local-administrator"}
	resolution := release.Resolution{Versions: map[string]string{"authorization_domain": "local-workbench"}, GatewayNamespace: ns, IngressClass: "higress", HostSuffix: "local.invalid", EndpointDNS: "no-model.local.invalid", EndpointPort: 443, CredentialHandle: "metadata-only-unavailable", PluginDigest: strings.Repeat("0", 64)}
	registry := localMetadataRegistry{management.Registry{Access: access, Entries: []management.RegistryEntry{{Namespace: ns, Spec: example.Spec, Resolution: resolution}, {Namespace: ns, Spec: second.Spec, Resolution: resolution}}}}
	hr := &history.Reader{DB: connections.History, PayloadDB: connections.Payload, Cluster: "local-workbench", Access: access, CursorKey: cursor, Live: history.KubeLive{Reader: kube}}
	hr.Evaluator = history.ResolverEvaluator{Resolver: registry, Loader: hr}
	operations := &management.Operations{DB: connections.Operations, Cluster: "local-workbench", Access: access}
	service := &management.Service{Client: kube, Reader: kube, Operations: operations, History: hr, Resolver: registry, Access: access, CursorKey: cursor}
	if _, e = service.Submit(ctx, "POST", ns, example.Name, "", "", "", example); e != nil {
		return e
	}
	reconciler := &release.Reconciler{Client: kube, Reader: kube, Dependencies: release.Dependencies{Control: publisher, Inventory: publisher, Resolver: registry, Bundle: localBundle{}, Plugin: unavailableGateway{}}}
	workerDone := make(chan struct{})
	go func() {
		defer close(workerDone)
		registered := map[string]bool{}
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			var list api.ModelReleaseList
			if kube.List(ctx, &list, client.InNamespace(ns)) == nil {
				for _, m := range list.Items {
					_, _ = reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKeyFromObject(&m)})
					state, err := publisher.Read(ctx, string(m.UID))
					if err == nil && state.Candidate != nil && !registered[state.Candidate.PublicationID] {
						p := kernel.Profile{CRUID: string(m.UID), Namespace: ns, Name: m.Name, Alias: m.Spec.ModelAlias, Binding: *state.Candidate, SourceID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(m.UID)).String(), SourceType: "external", UpstreamModel: m.Spec.Source.ExternalAPI.UpstreamModel, ConfigRevision: "local-metadata-v1", CapabilityRevision: "local-capability-v1", RouteDigest: strings.Repeat("0", 64), GatewayEpoch: 1, ApprovalRef: "local-metadata-only", Catalog: &kernel.CatalogMetadata{DisplayName: "本地管理示例（未接模型）", Capabilities: map[string]any{"streaming": true, "verified_max_output_tokens": 100, "temperature_supported": false, "usage_available": "unknown", "capability_revision": "local-capability-v1", "hard_budget_status": "unverified", "budget_unavailable_reason": "未接入真实网关与模型", "protocols": []string{"chat_completions"}}}}
						if core.RegisterProfile(ctx, p) == nil {
							registered[p.Binding.PublicationID] = true
						}
					}
				}
			}
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
		}
	}()
	defer func() { cancel(); <-workerDone }()
	listener, e := net.Listen("tcp", *address)
	if e != nil {
		return errors.New("workbench port already in use")
	}
	defer listener.Close()
	origin := "http://" + listener.Addr().String()
	session := workbench.NewLocalSession(origin)
	adminHandler := controlapi.Handler{Core: core, Sessions: session, Releases: service, Revisions: hr, Models: core, ModelGate: publisher, ModelNamespaces: access.Namespaces}
	input := map[string]any{"apiVersion": api.GroupVersion.String(), "kind": "ModelRelease", "metadata": map[string]any{"namespace": ns, "name": example.Name}, "spec": example.Spec}
	server := &http.Server{Handler: workbench.Handler(adminHandler, session, filepath.Join(*root, "console", "dist"), input), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second}
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	ready, _ := json.Marshal(map[string]any{"event": "ready", "url": origin, "mode": "local", "inference_available": false})
	fmt.Println(string(ready))
	select {
	case <-ctx.Done():
	case e = <-done:
		if !errors.Is(e, http.ErrServerClosed) {
			return e
		}
	}
	shutdown, finish := context.WithTimeout(context.Background(), 10*time.Second)
	defer finish()
	return server.Shutdown(shutdown)
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, "workbench:", e)
		os.Exit(1)
	}
}
