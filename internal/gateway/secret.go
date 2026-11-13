// Package gateway contains installation-side adapters. Stock Higress 2.2.5
// does not understand these contracts; production wiring remains closed.
package gateway

import (
	"context"
	"errors"
	"sync"
)

var ErrDependency = errors.New("gateway dependency missing")

type SecretRef struct{ Namespace, Name, UID, ResourceVersion, DataKey string }
type CredentialBinding struct {
	Handle, PublicationID, InstanceID string
	Epoch                             int64
	Secret                            SecretRef
}
type SecretValue struct {
	UID, ResourceVersion string
	Value                []byte
}

// SecretReader uses PREEXISTING approved namespaced RBAC. Returning both metadata
// and bytes prevents GET of a newer version silently rotating an old publication.
type SecretReader interface {
	Read(context.Context, SecretRef) (SecretValue, error)
}
type SecretAgent struct {
	mu      sync.RWMutex
	reader  SecretReader
	allowed map[string]CredentialBinding
	cache   map[string][]byte
}

func NewSecretAgent(reader SecretReader, bindings []CredentialBinding) (*SecretAgent, error) {
	if reader == nil {
		return nil, ErrDependency
	}
	a := &SecretAgent{reader: reader, allowed: map[string]CredentialBinding{}, cache: map[string][]byte{}}
	for _, b := range bindings {
		if b.Handle == "" || b.PublicationID == "" || b.InstanceID == "" || b.Epoch < 1 || b.Secret.Namespace == "" || b.Secret.Name == "" || b.Secret.UID == "" || b.Secret.ResourceVersion == "" || b.Secret.DataKey == "" {
			return nil, ErrDependency
		}
		if _, ok := a.allowed[b.Handle]; ok {
			return nil, ErrDependency
		}
		a.allowed[b.Handle] = b
	}
	return a, nil
}

// Lookup is called ONLY after the local plugin channel authenticates its peer.
// The agent never proxies model data or persists a plaintext value/value hash.
func (a *SecretAgent) Lookup(ctx context.Context, b CredentialBinding) ([]byte, error) {
	a.mu.RLock()
	allowed, ok := a.allowed[b.Handle]
	cached := append([]byte(nil), a.cache[b.Handle]...)
	a.mu.RUnlock()
	if !ok || b != allowed {
		return nil, ErrDependency
	}
	if len(cached) > 0 {
		return cached, nil
	}
	v, e := a.reader.Read(ctx, b.Secret)
	if e != nil || v.UID != b.Secret.UID || v.ResourceVersion != b.Secret.ResourceVersion || len(v.Value) == 0 || len(v.Value) > 8192 {
		return nil, ErrDependency
	}
	for _, c := range v.Value {
		if c == '\r' || c == '\n' || c == 0 {
			return nil, ErrDependency
		}
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.allowed[b.Handle] != b {
		return nil, ErrDependency
	}
	a.cache[b.Handle] = append([]byte(nil), v.Value...)
	return append([]byte(nil), v.Value...), nil
}

// Revocation clears the cached copy; it does not prove an existing transport stopped.
func (a *SecretAgent) Revoke(handle string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	for i := range a.cache[handle] {
		a.cache[handle][i] = 0
	}
	delete(a.cache, handle)
	delete(a.allowed, handle)
}
