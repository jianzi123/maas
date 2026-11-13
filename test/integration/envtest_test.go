//go:build envtest

package integration

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	api "github.com/jianzi123/maas/api/v1alpha1"
	releaseadmission "github.com/jianzi123/maas/internal/admission"
	"github.com/jianzi123/maas/internal/release"
	admissionregistrationv1 "k8s.io/api/admissionregistration/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/wait"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
	"sigs.k8s.io/yaml"
)

// Explicit opt-in only; never reuses KUBECONFIG or creates a target cluster.
// The approved resolver below is TEST ONLY; manager release ports stay absent.
func TestCRDCELAndResourceVersion(t *testing.T) {
	if os.Getenv("KUBEBUILDER_ASSETS") == "" {
		t.Fatal("authorized temporary envtest binaries required")
	}
	useExisting := false
	e := &envtest.Environment{UseExistingCluster: &useExisting, CRDDirectoryPaths: []string{filepath.Join("..", "..", "config", "crd")}, ErrorIfCRDPathMissing: true}
	t.Cleanup(func() {
		if err := e.Stop(); err != nil {
			t.Error(err)
		}
	})
	cfg, err := e.Start()
	if err != nil {
		t.Fatal(err)
	}
	s := runtime.NewScheme()
	_ = api.AddToScheme(s)
	_ = corev1.AddToScheme(s)
	_ = admissionregistrationv1.AddToScheme(s)
	c, err := client.New(cfg, client.Options{Scheme: s})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err = c.Create(ctx, &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "maas-models-example"}}); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile("../../config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	m := new(api.ModelRelease)
	if err = yaml.Unmarshal(b, m); err != nil {
		t.Fatal(err)
	}
	if err = c.Create(ctx, m); err != nil {
		t.Fatal(err)
	}
	original := m.DeepCopy()
	m.Spec.ModelAlias = "cannot-change"
	if err = c.Update(ctx, m); !apierrors.IsInvalid(err) {
		t.Fatalf("CEL immutable alias: %v", err)
	}
	m = original.DeepCopy()
	m.Spec.Lifecycle.DesiredState = "Paused"
	if err = c.Update(ctx, m); err != nil {
		t.Fatal(err)
	}
	original.Spec.Lifecycle.DesiredState = "Paused"
	if err = c.Update(ctx, original); !apierrors.IsConflict(err) {
		t.Fatalf("stale resourceVersion: %v", err)
	}
	m.Spec.Source.Type = "SelfHosted"
	if err = c.Update(ctx, m); !apierrors.IsInvalid(err) {
		t.Fatalf("CEL source: %v", err)
	}
	// Real TLS webhook transport and running controller manager on the temporary
	// API-server. No gateway or budget adapter is installed in this manager.
	options := e.WebhookInstallOptions
	mgr, err := ctrl.NewManager(cfg, ctrl.Options{Scheme: s, Metrics: metricsserver.Options{BindAddress: "0"}, HealthProbeBindAddress: "0", WebhookServer: webhook.NewServer(webhook.Options{Host: options.LocalServingHost, Port: options.LocalServingPort, CertDir: options.LocalServingCertDir})})
	if err != nil {
		t.Fatal(err)
	}
	r := &release.Reconciler{}
	if err = r.SetupWithManager(mgr); err != nil {
		t.Fatal(err)
	}
	mgr.GetWebhookServer().Register("/validate-modelrelease", &admission.Webhook{Handler: releaseadmission.Handler{Resolver: testApprovedResolver{}}})
	managerCtx, cancel := context.WithCancel(ctx)
	done := make(chan error, 1)
	go func() { done <- mgr.Start(managerCtx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(20 * time.Second):
			t.Error("manager did not stop")
		}
	})
	if err = wait.PollUntilContextTimeout(ctx, 100*time.Millisecond, 10*time.Second, true, func(context.Context) (bool, error) { return mgr.GetWebhookServer().StartedChecker()(nil) == nil, nil }); err != nil {
		t.Fatal(err)
	}
	u := url.URL{Scheme: "https", Host: fmt.Sprintf("%s:%d", options.LocalServingHost, options.LocalServingPort), Path: "/validate-modelrelease"}
	webhookURL := u.String()
	fail := admissionregistrationv1.Fail
	none := admissionregistrationv1.SideEffectClassNone
	scope := admissionregistrationv1.NamespacedScope
	config := &admissionregistrationv1.ValidatingWebhookConfiguration{ObjectMeta: metav1.ObjectMeta{Name: "maas-envtest-validation"}, Webhooks: []admissionregistrationv1.ValidatingWebhook{{Name: "modelrelease.serving.maas.example", AdmissionReviewVersions: []string{"v1"}, SideEffects: &none, FailurePolicy: &fail, ClientConfig: admissionregistrationv1.WebhookClientConfig{URL: &webhookURL, CABundle: options.LocalServingCAData}, Rules: []admissionregistrationv1.RuleWithOperations{{Operations: []admissionregistrationv1.OperationType{admissionregistrationv1.Create, admissionregistrationv1.Update}, Rule: admissionregistrationv1.Rule{APIGroups: []string{api.Group}, APIVersions: []string{"v1alpha1"}, Resources: []string{"modelreleases"}, Scope: &scope}}}}}}
	if err = c.Create(ctx, config); err != nil {
		t.Fatal(err)
	}
	live := new(api.ModelRelease)
	if err = yaml.Unmarshal(b, live); err != nil {
		t.Fatal(err)
	}
	live.Name = "live-manager"
	if err = c.Create(ctx, live); err != nil {
		t.Fatal(err)
	}
	if err = wait.PollUntilContextTimeout(ctx, 100*time.Millisecond, 15*time.Second, true, func(ctx context.Context) (bool, error) {
		if err := c.Get(ctx, client.ObjectKeyFromObject(live), live); err != nil {
			return false, err
		}
		return len(live.Finalizers) > 0 && live.Status.Phase == "Degraded" && live.Status.ObservedGeneration == live.Generation, nil
	}); err != nil {
		t.Fatalf("controller failed to project fail-closed status: %v; finalizers=%v status=%+v", err, live.Finalizers, live.Status)
	}
	for _, condition := range live.Status.Conditions {
		if condition.Type == "Callable" && condition.Status == metav1.ConditionTrue {
			t.Fatal("missing dependencies became callable")
		}
	}
	live.Spec.Source.ExternalAPI.EndpointRef.Revision = "unapproved"
	// The API-server's webhook registration cache is eventually consistent. Poll
	// for the explicit webhook denial, not a transient failure or schema error.
	if err = wait.PollUntilContextTimeout(ctx, 100*time.Millisecond, 10*time.Second, true, func(ctx context.Context) (bool, error) {
		probe := live.DeepCopy()
		err := c.Update(ctx, probe, client.DryRunAll)
		return err != nil && strings.Contains(err.Error(), "ProfileUnapproved"), nil
	}); err != nil {
		t.Fatal("webhook did not reject unapproved endpoint", err)
	}
}

type testApprovedResolver struct{}

func (testApprovedResolver) Resolve(_ context.Context, m *api.ModelRelease) (release.Resolution, error) {
	if m.Spec.Source.ExternalAPI == nil || m.Spec.Source.ExternalAPI.EndpointRef.Revision != "example-v1" {
		return release.Resolution{}, errors.New("unapproved test dependency")
	}
	return release.Resolution{}, nil
}
