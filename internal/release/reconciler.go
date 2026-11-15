package release

import (
	"context"
	"encoding/json"
	"reflect"
	"sort"

	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

const Finalizer = api.Group + "/release-cleanup"

type Reconciler struct {
	Client client.Client
	// Reader MUST be the uncached API reader. Finalizer and generation checks
	// cannot rely on a potentially stale controller-runtime cache.
	Reader client.Reader
	Dependencies
}

func (r *Reconciler) SetupWithManager(m ctrl.Manager) error {
	r.Client = m.GetClient()
	r.Reader = m.GetAPIReader()
	return ctrl.NewControllerManagedBy(m).For(&api.ModelRelease{}).Complete(r)
}
func (r *Reconciler) fresh(ctx context.Context, m *api.ModelRelease) error {
	n := new(api.ModelRelease)
	if err := r.Reader.Get(ctx, client.ObjectKeyFromObject(m), n); err != nil {
		return err
	}
	if n.UID != m.UID || n.Generation != m.Generation || !reflect.DeepEqual(n.Spec, m.Spec) || !n.DeletionTimestamp.Equal(m.DeletionTimestamp) || !controllerutil.ContainsFinalizer(n, Finalizer) {
		return ErrConflict
	}
	return nil
}
func command(s State, action string, target *Binding) Command {
	c := Command{Action: action, CRUID: s.CRUID, Generation: s.Generation, Fence: s.Fence, Revision: s.Revision, EvidenceRefs: append([]string{}, s.EvidenceRefs...)}
	if s.Active != nil {
		v := s.Active.PublicationID
		c.ExpectedActive = &v
	}
	if target != nil {
		v := target.PublicationID
		c.Target = &v
	}
	// Content-addressed UUID: same ID always means byte-equivalent command.
	sort.Strings(c.EvidenceRefs)
	data, _ := json.Marshal(c)
	c.ID = uuid.NewSHA1(uuid.NameSpaceOID, data).String()
	return c
}
func (r *Reconciler) apply(ctx context.Context, m *api.ModelRelease, s State, action string, target *Binding) error {
	if err := r.fresh(ctx, m); err != nil {
		return err
	}
	c := command(s, action, target)
	if err := ValidateCommand(c); err != nil {
		return err
	}
	return r.Control.Apply(ctx, c)
}
func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	m := new(api.ModelRelease)
	if r.Reader == nil {
		return ctrl.Result{}, ErrDependencyMissing
	}
	if err := r.Reader.Get(ctx, req.NamespacedName, m); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}
	if m.DeletionTimestamp != nil && !controllerutil.ContainsFinalizer(m, Finalizer) {
		return ctrl.Result{}, nil
	}
	if !controllerutil.ContainsFinalizer(m, Finalizer) {
		controllerutil.AddFinalizer(m, Finalizer)
		if err := r.Client.Update(ctx, m); err != nil {
			return ctrl.Result{}, err
		}
		// A separate authoritative read on the next pass confirms persistence.
		return ctrl.Result{RequeueAfter: RetryAfter}, nil
	}
	oldStatus := m.DeepCopy().Status
	m.Status.ObservedGeneration = m.Generation
	m.Status.Phase = "Preparing"
	m.Status.Resources = []api.ResourceRef{}
	for _, t := range []string{"Accepted", "DependenciesReady", "RuntimeReady", "GatewayApplied", "AccountingReady", "ValidationPassed", "Callable", "Progressing", "Degraded", "AdmissionClosed", "Drained", "CleanupComplete"} {
		setCondition(m, t, false, "Pending")
	}
	finish := func(phase, reason string, err error) (ctrl.Result, error) {
		m.Status.Phase = phase
		sort.Slice(m.Status.Resources, func(i, j int) bool {
			a, b := m.Status.Resources[i], m.Status.Resources[j]
			return a.APIVersion+"/"+a.Kind+"/"+a.Namespace+"/"+a.Name < b.APIVersion+"/"+b.Kind+"/"+b.Namespace+"/"+b.Name
		})
		if reason != "" {
			setCondition(m, "Callable", false, reason)
			setCondition(m, "Degraded", true, reason)
		}
		for i := range m.Status.Conditions {
			c := &m.Status.Conditions[i]
			for _, prior := range oldStatus.Conditions {
				if c.Type == prior.Type && c.Status == prior.Status {
					c.LastTransitionTime = prior.LastTransitionTime
				}
			}
		}
		// Do not emit untrusted backend/provider errors in status or logs.
		if !reflect.DeepEqual(oldStatus, m.Status) {
			if e := r.fresh(ctx, m); e != nil {
				return ctrl.Result{}, e
			}
			if e := r.Client.Status().Update(ctx, m); e != nil {
				return ctrl.Result{}, e
			}
		}
		if apierrors.IsConflict(err) {
			return ctrl.Result{}, err
		}
		return ctrl.Result{RequeueAfter: RetryAfter}, nil
	}
	uid := string(m.UID)
	desired := Desired{CRUID: uid, Namespace: m.Namespace, Name: m.Name, Alias: m.Spec.ModelAlias, Gateway: m.Spec.GatewayRef, Generation: m.Generation, Deleting: m.DeletionTimestamp != nil, Paused: m.Spec.Lifecycle.DesiredState == "Paused"}
	// A never-published paused/deleting CR still needs a shape-valid audit intent.
	// This unresolved digest cannot be a candidate or authorize activation. Control
	// preserves an existing resolved revision for an already prepared publication.
	desired.Revision = Hash(struct{ UnresolvedClosure api.Spec }{m.Spec})
	if r.Control == nil || r.Inventory == nil || r.Bundle == nil {
		if r.Control != nil {
			r.closeUnsafe(ctx, m)
		}
		return finish("Degraded", "DependencyMissing", ErrDependencyMissing)
	}
	if !desired.Deleting && !desired.Paused {
		if err := r.Dependencies.Check(); err != nil {
			r.closeUnsafe(ctx, m)
			return finish("Degraded", "DependencyMissing", err)
		}
	}
	var resolution Resolution
	if !desired.Deleting && !desired.Paused {
		if err := api.Validate(m.Spec, nil); err != nil {
			r.closeUnsafe(ctx, m)
			return finish("Failed", "InvalidSpec", err)
		}
		setCondition(m, "Accepted", true, "Accepted")
		var err error
		resolution, err = r.Resolver.Resolve(ctx, m)
		if err != nil {
			r.closeUnsafe(ctx, m)
			return finish("Degraded", "DependencyMissing", err)
		}
		desired.Revision = Revision(m.Spec, resolution)
		desired.History = &HistoryCapture{Spec: m.DeepCopy().Spec, Resolution: resolution, ResourceVersion: m.ResourceVersion, AuthorizationDomain: resolution.Versions["authorization_domain"]}
		m.Status.DesiredRevision = &desired.Revision
	}
	if err := r.fresh(ctx, m); err != nil {
		return ctrl.Result{}, err
	}
	s, err := r.Control.Observe(ctx, desired)
	if err != nil {
		return finish("Degraded", "AccountingUnavailable", err)
	}
	if s.CRUID != uid || s.Generation != m.Generation || s.Fence < 1 {
		return finish("Degraded", "RevisionConflict", ErrConflict)
	}
	projectActive(m, s)
	if desired.Deleting || desired.Paused {
		// Close does not need approved profiles or a Secret that may have vanished.
		if err = r.apply(ctx, m, s, "CloseAdmission", nil); err != nil {
			return finish("Draining", "CleanupBlocked", err)
		}
		s, err = r.Control.Read(ctx, uid)
		if err != nil || !s.AdmissionClosed || (desired.Deleting && !s.Tombstone) {
			return finish("Draining", "CleanupBlocked", err)
		}
		setCondition(m, "AdmissionClosed", true, "AdmissionClosed")
		safe, e := r.Control.Drain(ctx, uid, "")
		if e != nil || !safe {
			return finish("Draining", "CleanupBlocked", e)
		}
		setCondition(m, "Drained", true, "Drained")
		if err = r.cleanup(ctx, m, ""); err != nil {
			return finish("Draining", "CleanupBlocked", err)
		}
		if err = r.apply(ctx, m, s, "RecordCleanup", nil); err != nil {
			return finish("Draining", "CleanupBlocked", err)
		}
		setCondition(m, "CleanupComplete", true, "CleanupComplete")
		if desired.Deleting {
			if err = r.fresh(ctx, m); err != nil {
				return ctrl.Result{}, err
			}
			controllerutil.RemoveFinalizer(m, Finalizer)
			return ctrl.Result{}, r.Client.Update(ctx, m)
		}
		return finish("Paused", "", nil)
	}
	if s.Revision != desired.Revision || s.Candidate == nil || s.Candidate.Revision != desired.Revision || s.Candidate.Generation != m.Generation {
		return finish("Degraded", "RevisionConflict", ErrConflict)
	}
	b := *s.Candidate
	if s.Tombstone {
		return finish("Degraded", "RevisionConflict", ErrConflict)
	}
	if m.Spec.Lifecycle.Strategy == "Recreate" && s.Active != nil && s.Active.PublicationID != b.PublicationID {
		if err = r.apply(ctx, m, s, "CloseAdmission", s.Active); err != nil {
			return finish("Draining", "CleanupBlocked", err)
		}
		closed, e := r.Control.Read(ctx, uid)
		if e != nil || !closed.AdmissionClosed {
			return finish("Draining", "CleanupBlocked", e)
		}
		safe, e := r.Control.Drain(ctx, uid, s.Active.PublicationID)
		if e != nil || !safe {
			return finish("Draining", "CleanupBlocked", e)
		}
		if err = r.cleanup(ctx, m, s.Active.PublicationID); err != nil {
			return finish("Draining", "CleanupBlocked", err)
		}
	}
	plan, err := Compile(m, resolution, b)
	if err != nil {
		return finish("Degraded", "DependencyMissing", err)
	}
	if !plan.Deployable {
		return finish("Pending", "DependencyMissing", ErrDependencyMissing)
	}
	plugin, err := r.Plugin.Compile(ctx, m, resolution, b, nameFor(uid, b.PublicationID))
	if err != nil || plugin == nil {
		return finish("Degraded", "DependencyMissing", err)
	}
	// Only publication-scoped gateway plugin objects, no runtime from this port.
	if plugin.GetKind() != "WasmPlugin" || plugin.GetAPIVersion() != "extensions.higress.io/v1alpha1" || plugin.GetNamespace() != resolution.GatewayNamespace || plugin.GetName() != nameFor(uid, b.PublicationID) {
		return finish("Failed", "InvalidSpec", ErrOwnership)
	}
	plan.Objects = append(plan.Objects, Seal(plugin, m, b))
	resources := Resources{Client: r.Client, Reader: r.Reader, Inventory: r.Inventory}
	for _, p := range plan.Objects {
		if err = r.fresh(ctx, m); err != nil {
			return ctrl.Result{}, err
		}
		if err = resources.Ensure(ctx, uid, b.PublicationID, p); err != nil {
			if s.Active != nil && s.Active.PublicationID == b.PublicationID {
				r.closeUnsafe(ctx, m)
			}
			return finish("Degraded", "ResourcesPending", err)
		}
	}
	if err = r.fresh(ctx, m); err != nil {
		return ctrl.Result{}, err
	}
	if err = r.Bundle.Ensure(ctx, uid, b, plan.Registry); err != nil {
		if s.Active != nil && s.Active.PublicationID == b.PublicationID {
			r.closeUnsafe(ctx, m)
		}
		return finish("Degraded", "GatewayNotApplied", err)
	}
	setCondition(m, "DependenciesReady", true, "DependenciesReady")
	// Read durable receipts after resource reconciliation. Object existence alone
	// cannot become RuntimeReady/GatewayApplied/AccountingReady/ValidationPassed.
	s, err = r.Control.Read(ctx, uid)
	if err != nil {
		return finish("Degraded", "AccountingUnavailable", err)
	}
	if !sameCandidate(s, desired, b) {
		return finish("Degraded", "RevisionConflict", ErrConflict)
	}
	for t, ok := range map[string]bool{"RuntimeReady": s.RuntimeReady, "GatewayApplied": s.GatewayApplied, "AccountingReady": s.AccountingReady, "ValidationPassed": s.ValidationPassed} {
		setCondition(m, t, ok, "EvidencePending")
	}
	if !s.RuntimeReady || !s.GatewayApplied || !s.AccountingReady {
		if s.Active != nil && s.Active.PublicationID == b.PublicationID {
			r.closeUnsafe(ctx, m)
		}
		return finish("Preparing", "DependencyMissing", nil)
	}
	if !s.ValidationPassed {
		if err = r.apply(ctx, m, s, "RequestValidation", &b); err != nil {
			return finish("Validating", "ValidationUnknown", err)
		}
		return finish("Validating", "ValidationPending", nil)
	}
	if s.Active == nil || s.Active.PublicationID != b.PublicationID || s.AdmissionClosed {
		if err = r.apply(ctx, m, s, "Activate", &b); err != nil {
			return finish("Degraded", "RevisionConflict", err)
		}
	}
	s, err = r.Control.Read(ctx, uid)
	if err != nil || !sameCandidate(s, desired, b) || s.Active == nil || *s.Active != b || s.AdmissionClosed || !s.RuntimeReady || !s.GatewayApplied || !s.AccountingReady || !s.ValidationPassed {
		return finish("Degraded", "RevisionConflict", err)
	}
	projectActive(m, s)
	entries, err := r.Inventory.List(ctx, uid, b.PublicationID)
	if err != nil {
		return finish("Degraded", "DependencyMissing", err)
	}
	for _, e := range entries {
		m.Status.Resources = append(m.Status.Resources, e.Ref)
	}
	for _, old := range s.Draining {
		if old.PublicationID == b.PublicationID {
			continue
		}
		safe, e := r.Control.Drain(ctx, uid, old.PublicationID)
		if e != nil || !safe {
			continue
		}
		if err = r.cleanup(ctx, m, old.PublicationID); err != nil {
			return finish("Updating", "CleanupBlocked", err)
		}
	}
	setCondition(m, "Callable", true, "ActiveBindingVerified")
	return finish("Ready", "", nil)
}
func sameCandidate(s State, d Desired, b Binding) bool {
	return s.CRUID == d.CRUID && s.Generation == d.Generation && s.Revision == d.Revision && !s.Tombstone && s.Candidate != nil && *s.Candidate == b
}

// Best effort close on detected active drift. If storage is unavailable the
// durable admission core must additionally enforce receipt freshness itself.
// We only report AdmissionClosed after an authoritative acknowledgement.
func (r *Reconciler) closeUnsafe(ctx context.Context, m *api.ModelRelease) {
	s, err := r.Control.Read(ctx, string(m.UID))
	if err != nil || s.CRUID != string(m.UID) || s.Active == nil {
		return
	}
	if err = r.apply(ctx, m, s, "CloseAdmission", s.Active); err != nil {
		return
	}
	closed, err := r.Control.Read(ctx, string(m.UID))
	if err == nil && closed.CRUID == string(m.UID) && closed.AdmissionClosed {
		setCondition(m, "AdmissionClosed", true, "AdmissionClosed")
	}
}
func projectActive(m *api.ModelRelease, s State) {
	m.Status.ActiveRevision = nil
	m.Status.PublicationID = nil
	m.Status.ActiveGeneration = nil
	m.Status.ActivationEpoch = 0
	if s.Active != nil {
		m.Status.ActiveRevision = &s.Active.Revision
		m.Status.PublicationID = &s.Active.PublicationID
		m.Status.ActiveGeneration = &s.Active.Generation
		m.Status.ActivationEpoch = s.Active.Epoch
	}
}
func setCondition(m *api.ModelRelease, t string, ok bool, reason string) {
	status := metav1.ConditionFalse
	if ok {
		status = metav1.ConditionTrue
	}
	meta.SetStatusCondition(&m.Status.Conditions, metav1.Condition{Type: t, Status: status, Reason: reason, Message: reason, ObservedGeneration: m.Generation})
}
func (r *Reconciler) cleanup(ctx context.Context, m *api.ModelRelease, pub string) error {
	if err := r.fresh(ctx, m); err != nil {
		return err
	}
	uid := string(m.UID)
	entries, err := r.Inventory.List(ctx, uid, pub)
	if err != nil {
		return err
	}
	// Removing a shared ENTRY cannot delete the McpBridge or another model.
	pubs := map[string]bool{}
	for _, e := range entries {
		pubs[e.Publication] = true
	}
	if pub != "" {
		pubs[pub] = true
	}
	for p := range pubs {
		if err = r.Bundle.Remove(ctx, uid, p); err != nil {
			return err
		}
	}
	resources := Resources{Client: r.Client, Reader: r.Reader, Inventory: r.Inventory}
	for _, e := range entries {
		if e.Owner != uid || (pub != "" && e.Publication != pub) {
			return ErrOwnership
		}
		if err = r.fresh(ctx, m); err != nil {
			return err
		}
		if err = resources.Delete(ctx, e); err != nil {
			return err
		}
	}
	remaining, err := r.Inventory.List(ctx, uid, pub)
	if err != nil {
		return err
	}
	if len(remaining) != 0 {
		return ErrConflict
	}
	return nil
}
