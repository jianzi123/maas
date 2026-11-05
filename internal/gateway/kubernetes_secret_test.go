package gateway

import (
	"context"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"testing"
)

func TestKubernetesSecretReaderVersionAndNamespace(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = corev1.AddToScheme(scheme)
	secret := &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "provider", Namespace: "approved", UID: types.UID("secret-uid"), ResourceVersion: "10"}, Data: map[string][]byte{"token": []byte("test-only-credential")}}
	r := KubernetesSecretReader{Reader: fake.NewClientBuilder().WithScheme(scheme).WithObjects(secret).Build(), ApprovedNamespaces: map[string]bool{"approved": true}}
	ref := SecretRef{Namespace: "approved", Name: "provider", UID: "secret-uid", ResourceVersion: "10", DataKey: "token"}
	v, e := r.Read(context.Background(), ref)
	if e != nil {
		t.Fatal(e)
	}
	v.Value[0] = 'X'
	again, e := r.Read(context.Background(), ref)
	if e != nil || again.Value[0] == 'X' {
		t.Fatal("mutable secret copy", e)
	}
	wrong := ref
	wrong.ResourceVersion = "11"
	if _, e = r.Read(context.Background(), wrong); e == nil {
		t.Fatal("wrong version")
	}
	wrong = ref
	wrong.Namespace = "other"
	if _, e = r.Read(context.Background(), wrong); e == nil {
		t.Fatal("cross namespace")
	}
	wrong = ref
	wrong.UID = "new-uid"
	if _, e = r.Read(context.Background(), wrong); e == nil {
		t.Fatal("recreated Secret")
	}
}
