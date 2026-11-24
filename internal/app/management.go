package app

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"os"
	"strings"

	"github.com/go-sql-driver/mysql"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release/history"
	"github.com/jianzi123/maas/internal/release/management"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/tools/clientcmd"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

func scopedDB(ctx context.Context, file, role, coreUser string, seen map[string]bool) (*sql.DB, error) {
	b, e := secret(file, 1, 8192)
	if e != nil {
		return nil, errors.New("management_dsn_unavailable")
	}
	cfg, e := mysql.ParseDSN(string(b))
	if e != nil || cfg.User == "" || strings.EqualFold(cfg.User, "root") || cfg.User == coreUser || seen[cfg.User] {
		return nil, errors.New("management_identity_must_be_independent")
	}
	db, e := openDB(ctx, file)
	if e != nil {
		return nil, e
	}
	var actual string
	if db.QueryRowContext(ctx, "SELECT CURRENT_ROLE()").Scan(&actual) != nil || actual != "`"+role+"`@`%`" {
		db.Close()
		return nil, errors.New("management_default_role_invalid")
	}
	seen[cfg.User] = true
	return db, nil
}

// wireManagement reuses the original Reader/Operations/Publisher factories. It
// never substitutes the core DB for projections, creates users, or supplies fake
// Kubernetes objects. Disabled means accurately unavailable management endpoints.
func (r *Runtime) wireManagement(ctx context.Context, c Config, h *controlapi.Handler, cursor []byte) error {
	if !c.Management.Enabled {
		return nil
	}
	m := c.Management
	b, e := secret(c.MySQL.RuntimeDSNFile, 1, 8192)
	if e != nil {
		return e
	}
	coreCfg, e := mysql.ParseDSN(string(b))
	if e != nil {
		return ErrConfig
	}
	seen := map[string]bool{}
	historyDB, e := scopedDB(ctx, m.HistoryDSNFile, "maas_release_history_reader", coreCfg.User, seen)
	if e != nil {
		return e
	}
	r.closers = append(r.closers, historyDB)
	payloadDB, e := scopedDB(ctx, m.PayloadDSNFile, "maas_history_payload_reader", coreCfg.User, seen)
	if e != nil {
		return e
	}
	r.closers = append(r.closers, payloadDB)
	operationsDB, e := scopedDB(ctx, m.OperationsDSNFile, "maas_release_operations_runtime", coreCfg.User, seen)
	if e != nil {
		return e
	}
	r.closers = append(r.closers, operationsDB)
	publisherBytes, e := secret(m.PublisherDSNFile, 1, 8192)
	if e != nil {
		return e
	}
	publisherCfg, e := mysql.ParseDSN(string(publisherBytes))
	if e != nil || publisherCfg.User == coreCfg.User || seen[publisherCfg.User] {
		return errors.New("publisher_identity_must_be_independent")
	}
	publisher, e := mysqlstore.OpenPublisher(ctx, string(publisherBytes), c.Cluster, r.Core)
	if e != nil {
		return e
	}
	r.closers = append(r.closers, publisher)
	access := history.NamespaceAccess{Namespaces: map[string]bool{}, Domains: map[string]bool{}, ScopeID: m.ScopeID}
	for _, ns := range m.Namespaces {
		access.Namespaces[ns] = true
	}
	for _, domain := range m.Domains {
		access.Domains[domain] = true
	}
	registry := &management.Registry{Access: access}
	raw, e := os.ReadFile(m.RegistryFile)
	if e != nil || len(raw) > 1<<20 {
		return errors.New("management_registry_unavailable")
	}
	raw, e = protocol.Canonical(raw)
	if e != nil {
		return errors.New("management_registry_invalid")
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if dec.Decode(registry) != nil || dec.Decode(new(any)) != io.EOF || len(registry.Entries) == 0 || len(registry.Entries) > 256 {
		return errors.New("management_registry_invalid")
	}
	registry.Access = access
	for _, entry := range registry.Entries {
		if api.Validate(entry.Spec, nil) != nil || !access.Namespaces[entry.Namespace] || !access.Domains[entry.Resolution.Versions["authorization_domain"]] {
			return errors.New("management_registry_scope_invalid")
		}
	}
	cfg, e := clientcmd.BuildConfigFromFlags("", m.KubeconfigFile)
	if e != nil {
		return errors.New("management_kubernetes_config_unavailable")
	}
	scheme := runtime.NewScheme()
	_ = api.AddToScheme(scheme)
	kube, e := client.New(cfg, client.Options{Scheme: scheme})
	if e != nil {
		return errors.New("management_kubernetes_reader_unavailable")
	}
	reader := &history.Reader{DB: historyDB, PayloadDB: payloadDB, Cluster: c.Cluster, Access: access, CursorKey: cursor, Live: history.KubeLive{Reader: kube}}
	reader.Evaluator = history.ResolverEvaluator{Resolver: registry, Loader: reader}
	operations := &management.Operations{DB: operationsDB, Cluster: c.Cluster, Access: access}
	h.Revisions = reader
	h.Releases = &management.Service{Client: kube, Reader: kube, Operations: operations, History: reader, Resolver: registry, Access: access, CursorKey: cursor}
	h.ModelGate = publisher.Store
	h.ModelNamespaces = access.Namespaces
	return nil
}
