// The review binary intentionally ships without production release adapters.
// It may be compiled locally; running against a target cluster needs authorization.
package main

import (
	"fmt"
	api "github.com/jianzi123/maas/api/v1alpha1"
	releaseadmission "github.com/jianzi123/maas/internal/admission"
	"github.com/jianzi123/maas/internal/release"
	"k8s.io/apimachinery/pkg/runtime"
	"net/http"
	"os"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
)

func run() error {
	scheme := runtime.NewScheme()
	if err := api.AddToScheme(scheme); err != nil {
		return err
	}
	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{Scheme: scheme, LeaderElection: true, LeaderElectionID: "maas-modelrelease-review", Metrics: metricsserver.Options{BindAddress: "0"}, HealthProbeBindAddress: "127.0.0.1:8081", WebhookServer: webhook.NewServer(webhook.Options{Port: 9443})})
	if err != nil {
		return err
	}
	reconciler := &release.Reconciler{} // nil adapters => DependencyMissing, no release
	if err = reconciler.SetupWithManager(mgr); err != nil {
		return err
	}
	mgr.GetWebhookServer().Register("/validate-modelrelease", &admission.Webhook{Handler: releaseadmission.Handler{}})
	if err = mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		return err
	}
	if err = mgr.AddReadyzCheck("release-dependencies", func(*http.Request) error { return release.ErrDependencyMissing }); err != nil {
		return err
	}
	return mgr.Start(ctrl.SetupSignalHandler())
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "operator stopped:", err)
		os.Exit(1)
	}
}
