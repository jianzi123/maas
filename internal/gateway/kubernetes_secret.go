package gateway

import (
	"context"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// KubernetesSecretReader performs an actual read through an injected K8s client.
// Namespace approval is installation input; it does not create/expand RBAC.
type KubernetesSecretReader struct {
	Reader             client.Reader
	ApprovedNamespaces map[string]bool
}

func (r KubernetesSecretReader) Read(ctx context.Context, ref SecretRef) (SecretValue, error) {
	if r.Reader == nil || !r.ApprovedNamespaces[ref.Namespace] {
		return SecretValue{}, ErrDependency
	}
	var s corev1.Secret
	if r.Reader.Get(ctx, types.NamespacedName{Namespace: ref.Namespace, Name: ref.Name}, &s) != nil || string(s.UID) != ref.UID || s.ResourceVersion != ref.ResourceVersion {
		return SecretValue{}, ErrDependency
	}
	value, ok := s.Data[ref.DataKey]
	if !ok {
		return SecretValue{}, ErrDependency
	}
	return SecretValue{UID: string(s.UID), ResourceVersion: s.ResourceVersion, Value: append([]byte(nil), value...)}, nil
}
