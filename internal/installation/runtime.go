// Package installation assembles existing ports. It supplies no proof producer,
// public listener, schema migration, user provisioning or production approval.
package installation

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/gateway"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

type Config struct {
	Cluster, PublisherDSNFile, SigningKeyFile string
	Kid, SignerOwner, Instance                string
	Epoch                                     int64
	Relay                                     kernel.RelayTLSFiles
	Credentials                               []gateway.CredentialBinding
}

// Registry must check the currently approved signer/instance/boot/source state.
// No implementation in this package manufactures that external fact.
type Registry interface {
	Check(context.Context, string, string, string, string, int64) error
}
type Dependencies struct {
	Core         *kernel.Store
	Registry     Registry
	SecretReader gateway.SecretReader
	Peer         func(*http.Request) bool
}

type Runtime struct {
	Publisher *mysqlstore.PublisherRuntime
	Relay     *kernel.Relay
	Secrets   *gateway.SecretAgent
	config    Config
	deps      Dependencies
	key       []byte
}

func LoadConfig(data []byte) (Config, error) {
	var c Config
	if len(data) == 0 || len(data) > 65536 {
		return c, gateway.ErrDependency
	}
	canonical, err := protocol.Canonical(data)
	if err != nil {
		return Config{}, gateway.ErrDependency
	}
	d := json.NewDecoder(bytes.NewReader(canonical))
	d.DisallowUnknownFields()
	if d.Decode(&c) != nil {
		return Config{}, gateway.ErrDependency
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return Config{}, gateway.ErrDependency
	}
	return c, nil
}
func privateFile(name string) ([]byte, error) {
	if name == "" {
		return nil, gateway.ErrDependency
	}
	f, e := os.Open(name)
	if e != nil {
		return nil, gateway.ErrDependency
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, 8193))
	if e != nil || len(b) == 0 || len(b) > 8192 {
		return nil, gateway.ErrDependency
	}
	return b, nil
}

func Open(ctx context.Context, c Config, d Dependencies) (*Runtime, error) {
	if len(c.Credentials) == 0 || c.Cluster == "" || c.Kid == "" || c.SignerOwner == "" || c.Instance == "" || c.Epoch < 1 || d.Core == nil || d.Registry == nil || d.SecretReader == nil || d.Peer == nil {
		return nil, gateway.ErrDependency
	}
	if d.Registry.Check(ctx, c.Cluster, c.Instance, c.Kid, c.SignerOwner, c.Epoch) != nil {
		return nil, gateway.ErrDependency
	}
	for _, b := range c.Credentials {
		if b.InstanceID != c.Instance || b.Epoch != c.Epoch {
			return nil, gateway.ErrDependency
		}
	}
	secrets, e := gateway.NewSecretAgent(d.SecretReader, c.Credentials)
	if e != nil {
		return nil, gateway.ErrDependency
	}
	key, e := privateFile(c.SigningKeyFile)
	if e != nil || len(key) < 32 {
		return nil, gateway.ErrDependency
	}
	dsn, e := privateFile(c.PublisherDSNFile)
	if e != nil {
		return nil, gateway.ErrDependency
	}
	defer func() {
		for i := range dsn {
			dsn[i] = 0
		}
	}()
	relay, e := kernel.OpenRelayTLS(d.Core, c.Relay)
	if e != nil {
		return nil, gateway.ErrDependency
	}
	pub, e := mysqlstore.OpenPublisher(ctx, string(bytes.TrimSpace(dsn)), c.Cluster, d.Core)
	if e != nil {
		relay.Close()
		return nil, gateway.ErrDependency
	}
	return &Runtime{Publisher: pub, Relay: relay, Secrets: secrets, config: c, deps: d, key: key}, nil
}

// Authorizer is an INTERNAL mTLS handler. Register only on the approved private
// listener; no debug inference endpoint is supplied. Candidate purpose stays
// bound to the original durable intent checked by Core.Admit.
func (r *Runtime) Authorizer(validationIntent string) (http.Handler, error) {
	if validationIntent != "" {
		if id, e := uuid.Parse(validationIntent); e != nil || id.String() != validationIntent {
			return nil, gateway.ErrDependency
		}
	}
	a := &gateway.Authorizer{ValidationIntentID: validationIntent, Core: r.deps.Core, Gate: r.Publisher.Store, Key: r.key, Kid: r.config.Kid, SignerOwner: r.config.SignerOwner, Instance: r.config.Instance, Epoch: r.config.Epoch, Peer: r.deps.Peer}
	return http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) {
		if r.deps.Registry.Check(q.Context(), r.config.Cluster, r.config.Instance, r.config.Kid, r.config.SignerOwner, r.config.Epoch) != nil {
			w.Header().Set("Cache-Control", "no-store")
			w.WriteHeader(503)
			return
		}
		a.ServeHTTP(w, q)
	}), nil
}
func (r *Runtime) Close() {
	r.Relay.Close()
	_ = r.Publisher.Close()
	for _, b := range r.config.Credentials {
		r.Secrets.Revoke(b.Handle)
	}
}
