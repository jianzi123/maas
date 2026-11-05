package release

// All in-memory adapters in this file are TEST ONLY. Their booleans are not
// production receipts and these tests do not establish MySQL/K8s atomicity.
import (
	"context"
	"errors"
	"os"
	"reflect"
	"testing"

	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
	"sigs.k8s.io/yaml"
)

type resolver struct {
	version string
	fail    bool
}

func (r *resolver) Resolve(context.Context, *api.ModelRelease) (Resolution, error) {
	if r.fail {
		return Resolution{}, ErrDependencyMissing
	}
	return Resolution{Versions: map[string]string{"approved-registry": "1", "secretUID": "secret-uid", "secretResourceVersion": r.version}, GatewayNamespace: "higress-test", IngressClass: "private", HostSuffix: "infer.test", EndpointDNS: "provider.test", EndpointPort: 443, CredentialHandle: "opaque-test-handle", PluginDigest: "sha256:test-only"}, nil
}

type plugin struct{}

func (plugin) Compile(_ context.Context, _ *api.ModelRelease, r Resolution, _ Binding, name string) (*unstructured.Unstructured, error) {
	return &unstructured.Unstructured{Object: map[string]any{"apiVersion": "extensions.higress.io/v1alpha1", "kind": "WasmPlugin", "metadata": map[string]any{"namespace": r.GatewayNamespace, "name": name}, "spec": map[string]any{"TEST_ONLY": "not-a-production-gateway-config"}}}, nil
}

type control struct {
	states            map[string]State
	desired           map[string]Desired
	commands          map[string]string
	validations       map[string]bool
	automaticEvidence bool
	safe              bool
	alias             map[string]string
	activationLost    bool
	activationCount   int
}

func newControl() *control {
	return &control{states: map[string]State{}, desired: map[string]Desired{}, commands: map[string]string{}, validations: map[string]bool{}, automaticEvidence: true, safe: true, alias: map[string]string{}}
}
func (c *control) Observe(_ context.Context, d Desired) (State, error) {
	s := c.states[d.CRUID]
	key := d.Gateway.Name + "/" + d.Alias
	if owner := c.alias[key]; owner != "" && owner != d.CRUID {
		return State{}, ErrConflict
	}
	c.alias[key] = d.CRUID
	if s.Tombstone && !d.Deleting {
		return State{}, ErrConflict
	}
	// ResourceVersion is audit provenance, not desired-state identity.
	identity := d
	identity.History = nil
	prior, exists := c.desired[d.CRUID]
	if exists && d.Generation < prior.Generation {
		return State{}, ErrConflict
	}
	if !exists || !reflect.DeepEqual(prior, identity) {
		s.CRUID = d.CRUID
		s.Generation = d.Generation
		s.Fence++
		if s.Revision == "" {
			s.Revision = d.Revision
		}
		if !d.Deleting && !d.Paused {
			epoch := int64(1)
			if s.Candidate != nil {
				epoch = s.Candidate.Epoch + 1
			}
			s.Revision = d.Revision
			s.Candidate = &Binding{PublicationID: uuid.NewString(), Revision: d.Revision, Generation: d.Generation, Epoch: epoch}
			s.RuntimeReady = c.automaticEvidence
			s.GatewayApplied = c.automaticEvidence
			s.AccountingReady = c.automaticEvidence
			s.ValidationPassed = c.automaticEvidence
			s.EvidenceRefs = []string{uuid.NewString()}
		}
		if s.Active == nil {
			s.AdmissionClosed = true
		}
		c.desired[d.CRUID] = identity
		c.states[d.CRUID] = s
	}
	return s, nil
}
func (c *control) Read(_ context.Context, uid string) (State, error) { return c.states[uid], nil }
func (c *control) Apply(_ context.Context, cmd Command) error {
	digest := Hash(cmd)
	if prior, ok := c.commands[cmd.ID]; ok {
		if prior != digest {
			return ErrConflict
		}
		return nil
	}
	s := c.states[cmd.CRUID]
	if s.Generation != cmd.Generation || s.Fence != cmd.Fence {
		return ErrConflict
	}
	active := ""
	if s.Active != nil {
		active = s.Active.PublicationID
	}
	expected := ""
	if cmd.ExpectedActive != nil {
		expected = *cmd.ExpectedActive
	}
	if active != expected {
		return ErrConflict
	}
	switch cmd.Action {
	case "RequestValidation":
		if cmd.Target == nil {
			return ErrConflict
		}
		c.validations[*cmd.Target] = true
	case "Activate":
		if s.Tombstone || s.Candidate == nil || cmd.Target == nil || *cmd.Target != s.Candidate.PublicationID || !s.RuntimeReady || !s.GatewayApplied || !s.AccountingReady || !s.ValidationPassed {
			return ErrConflict
		}
		if s.Active != nil {
			s.Draining = append(s.Draining, *s.Active)
		}
		b := *s.Candidate
		s.Active = &b
		s.AdmissionClosed = false
		c.activationCount++
	case "CloseAdmission":
		s.AdmissionClosed = true
		if c.desired[cmd.CRUID].Deleting {
			s.Tombstone = true
		}
	case "RecordCleanup":
	default:
		return errors.New("unsupported test command")
	}
	c.states[cmd.CRUID] = s
	c.commands[cmd.ID] = digest
	if cmd.Action == "Activate" && c.activationLost {
		c.activationLost = false
		return errors.New("simulated commit ACK loss")
	}
	return nil
}
func (c *control) Drain(context.Context, string, string) (bool, error) { return c.safe, nil }

type inventory struct {
	entries      map[string]Entry
	safe         *bool
	beforeCreate int
}

func entryKey(e Entry) string {
	return e.Owner + "/" + e.Publication + "/" + e.Ref.Kind + "/" + e.Ref.Namespace + "/" + e.Ref.Name
}
func (i *inventory) Intent(_ context.Context, e Entry) error {
	key := entryKey(e)
	if old, ok := i.entries[key]; ok {
		if old.Digest != e.Digest || old.Retiring {
			return ErrConflict
		}
		return nil
	}
	i.entries[key] = e
	i.beforeCreate++
	return nil
}
func (i *inventory) Bind(_ context.Context, e Entry) error {
	key := entryKey(e)
	old, ok := i.entries[key]
	if !ok || old.Digest != e.Digest || (old.Ref.UID != "" && old.Ref.UID != e.Ref.UID) || old.Retiring {
		return ErrOwnership
	}
	i.entries[key] = e
	return nil
}
func (i *inventory) List(_ context.Context, uid, pub string) ([]Entry, error) {
	out := []Entry{}
	for _, e := range i.entries {
		if e.Owner == uid && (pub == "" || pub == e.Publication) {
			out = append(out, e)
		}
	}
	return out, nil
}
func (i *inventory) Retire(_ context.Context, e Entry) error {
	if !*i.safe {
		return ErrConflict
	}
	e.Retiring = true
	i.entries[entryKey(e)] = e
	return nil
}
func (i *inventory) Removed(_ context.Context, e Entry) error {
	delete(i.entries, entryKey(e))
	return nil
}

type bundle struct{ entries map[string]RegistryEntry }

func (b *bundle) Ensure(_ context.Context, uid string, p Binding, e RegistryEntry) error {
	b.entries[uid+"/"+p.PublicationID] = e
	return nil
}
func (b *bundle) Remove(_ context.Context, uid, pub string) error {
	delete(b.entries, uid+"/"+pub)
	return nil
}

type harness struct {
	t              *testing.T
	r              *Reconciler
	m              *api.ModelRelease
	c              client.WithWatch
	control        *control
	inventory      *inventory
	bundle         *bundle
	resolver       *resolver
	conflict       bool
	statusConflict bool
	creates        int
}

func fixture(t *testing.T, source string) *api.ModelRelease {
	t.Helper()
	data, err := os.ReadFile("../../config/samples/MAAS-2-modelrelease-" + source + "-v0.4.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	m := new(api.ModelRelease)
	if err = yaml.UnmarshalStrict(data, m); err != nil {
		t.Fatal(err)
	}
	m.UID = types.UID(uuid.NewString())
	m.Generation = 1
	return m
}
func newHarness(t *testing.T) *harness {
	h := &harness{t: t, m: fixture(t, "externalapi"), control: newControl(), bundle: &bundle{entries: map[string]RegistryEntry{}}, resolver: &resolver{version: "1"}}
	h.inventory = &inventory{entries: map[string]Entry{}, safe: &h.control.safe}
	s := runtime.NewScheme()
	_ = api.AddToScheme(s)
	_ = corev1.AddToScheme(s)
	_ = networkingv1.AddToScheme(s)
	h.c = fake.NewClientBuilder().WithScheme(s).WithStatusSubresource(&api.ModelRelease{}).WithObjects(h.m).WithInterceptorFuncs(interceptor.Funcs{
		Create: func(ctx context.Context, c client.WithWatch, o client.Object, opts ...client.CreateOption) error {
			if h.inventory.beforeCreate <= h.creates {
				t.Fatal("resource created without durable inventory intent")
			}
			h.creates++
			if o.GetUID() == "" {
				o.SetUID(types.UID(uuid.NewString()))
			}
			return c.Create(ctx, o, opts...)
		},
		Update: func(ctx context.Context, c client.WithWatch, o client.Object, opts ...client.UpdateOption) error {
			if h.conflict {
				h.conflict = false
				return apierrors.NewConflict(schema.GroupResource{Group: api.Group, Resource: "modelreleases"}, o.GetName(), errors.New("injected conflict"))
			}
			return c.Update(ctx, o, opts...)
		},
		SubResourceUpdate: func(ctx context.Context, c client.Client, sub string, o client.Object, opts ...client.SubResourceUpdateOption) error {
			if h.statusConflict {
				h.statusConflict = false
				return apierrors.NewConflict(schema.GroupResource{Group: api.Group, Resource: "modelreleases"}, o.GetName(), errors.New("injected conflict"))
			}
			return c.SubResource(sub).Update(ctx, o, opts...)
		},
	}).Build()
	h.r = &Reconciler{Client: h.c, Reader: h.c, Dependencies: Dependencies{Resolver: h.resolver, Control: h.control, Inventory: h.inventory, Bundle: h.bundle, Plugin: plugin{}}}
	return h
}
func (h *harness) step() error {
	_, err := h.r.Reconcile(context.Background(), ctrl.Request{NamespacedName: client.ObjectKeyFromObject(h.m)})
	return err
}
func (h *harness) run() {
	h.t.Helper()
	if err := h.step(); err != nil {
		h.t.Fatal(err)
	}
}
func (h *harness) current() *api.ModelRelease {
	h.t.Helper()
	m := new(api.ModelRelease)
	if err := h.c.Get(context.Background(), client.ObjectKeyFromObject(h.m), m); err != nil {
		h.t.Fatal(err)
	}
	return m
}
func (h *harness) change(fn func(*api.ModelRelease)) {
	h.t.Helper()
	m := h.current()
	fn(m)
	m.Generation++
	if err := h.c.Update(context.Background(), m); err != nil {
		h.t.Fatal(err)
	}
}
func ready(t *testing.T, m *api.ModelRelease, want bool) {
	t.Helper()
	got := meta.IsStatusConditionTrue(m.Status.Conditions, "Callable")
	if got != want || (want && m.Status.Phase != "Ready") {
		t.Fatalf("phase %s, callable %v", m.Status.Phase, got)
	}
}

func TestExternalAPILifecycleAndRestart(t *testing.T) {
	h := newHarness(t)
	h.run()
	if h.creates != 0 {
		t.Fatal("resources before finalizer confirmation")
	}
	h.run()
	ready(t, h.current(), true)
	old := h.current()
	if h.creates != 2 {
		t.Fatalf("got %d objects", h.creates)
	}
	entries, _ := h.inventory.List(context.Background(), string(h.m.UID), "")
	for _, e := range entries {
		if e.Ref.Kind != "Ingress" && e.Ref.Kind != "WasmPlugin" {
			t.Fatal("external runtime object", e.Ref.Kind)
		}
	}
	// New controller instance, same durable adapters; no duplicate resource/activation.
	h.r = &Reconciler{Client: h.c, Reader: h.c, Dependencies: h.r.Dependencies}
	h.run()
	if h.creates != 2 || h.control.activationCount != 1 {
		t.Fatal("not idempotent after restart")
	}
	if !reflect.DeepEqual(old.Status, h.current().Status) {
		t.Fatal("stable reconcile churns status")
	}
	h.change(func(m *api.ModelRelease) { m.Spec.Source.ExternalAPI.UpstreamModel = "updated" })
	h.run()
	updated := h.current()
	ready(t, updated, true)
	if *old.Status.PublicationID == *updated.Status.PublicationID || updated.Status.ActivationEpoch <= old.Status.ActivationEpoch {
		t.Fatal("update reused publication/epoch")
	}
	h.change(func(m *api.ModelRelease) { m.Spec = old.Spec })
	h.run()
	rolled := h.current()
	ready(t, rolled, true)
	if *rolled.Status.PublicationID == *old.Status.PublicationID || rolled.Status.ActivationEpoch <= updated.Status.ActivationEpoch {
		t.Fatal("rollback did not allocate new activation")
	}
	h.change(func(m *api.ModelRelease) { m.Spec.Lifecycle.DesiredState = "Paused" })
	h.run()
	if h.current().Status.Phase != "Paused" || len(h.inventory.entries) != 0 {
		t.Fatal("pause did not close and clean")
	}
	h.change(func(m *api.ModelRelease) { m.Spec.Lifecycle.DesiredState = "Published" })
	h.run()
	ready(t, h.current(), true)
}
func TestGenerationCannotInheritReadyAndValidationIsUnique(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	old := h.current()
	h.control.automaticEvidence = false
	h.change(func(m *api.ModelRelease) { m.Spec.Source.ExternalAPI.UpstreamModel = "candidate" })
	h.run()
	m := h.current()
	ready(t, m, false)
	if m.Status.ActiveGeneration == nil || *m.Status.ActiveGeneration == m.Generation || *m.Status.PublicationID != *old.Status.PublicationID {
		t.Fatal("lost old active binding")
	}
	s := h.control.states[string(m.UID)]
	s.RuntimeReady = true
	s.GatewayApplied = true
	s.AccountingReady = true
	h.control.states[string(m.UID)] = s
	h.run()
	h.run()
	if len(h.control.validations) != 1 {
		t.Fatal("validation not unique")
	}
	if h.current().Status.Phase != "Validating" {
		t.Fatal("expected validation pending")
	}
	s.ValidationPassed = true
	h.control.states[string(m.UID)] = s
	h.run()
	ready(t, h.current(), true)
}
func TestMissingProductionDependenciesFailClosed(t *testing.T) {
	h := newHarness(t)
	h.r.Dependencies = Dependencies{}
	h.run()
	h.run()
	m := h.current()
	ready(t, m, false)
	if h.creates != 0 || m.Status.Phase != "Degraded" {
		t.Fatal("missing dependencies created resources")
	}
}
func TestNeverPublishedPauseDoesNotNeedCredentialResolution(t *testing.T) {
	h := newHarness(t)
	h.change(func(m *api.ModelRelease) { m.Spec.Lifecycle.DesiredState = "Paused" })
	h.r.Resolver = nil
	h.r.Plugin = nil
	h.run()
	h.run()
	if h.current().Status.Phase != "Paused" || h.creates != 0 {
		t.Fatal("fresh paused CR requires runtime credentials")
	}
}
func TestConflictRetryAndActivationCommitACKLoss(t *testing.T) {
	h := newHarness(t)
	h.conflict = true
	if !apierrors.IsConflict(h.step()) {
		t.Fatal("expected resourceVersion conflict")
	}
	if h.creates != 0 {
		t.Fatal("created before confirmed finalizer")
	}
	h.run()
	h.control.activationLost = true
	h.run()
	ready(t, h.current(), false)
	h.statusConflict = true
	if !apierrors.IsConflict(h.step()) {
		t.Fatal("expected status conflict")
	}
	h.run()
	ready(t, h.current(), true)
	if h.control.activationCount != 1 {
		t.Fatal("activation replayed after ACK loss")
	}
}
func TestDeletionWaitsForTransportAndSlot(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	h.control.safe = false
	m := h.current()
	if err := h.c.Delete(context.Background(), m); err != nil {
		t.Fatal(err)
	}
	h.run()
	m = h.current()
	if len(m.Finalizers) == 0 || len(h.inventory.entries) == 0 || !meta.IsStatusConditionTrue(m.Status.Conditions, "AdmissionClosed") {
		t.Fatal("unsafe cleanup")
	}
	// Missing Secret/profile cannot prevent closing or cleanup.
	h.r.Resolver = nil
	h.r.Plugin = nil
	h.control.safe = true
	h.run()
	err := h.c.Get(context.Background(), client.ObjectKeyFromObject(m), new(api.ModelRelease))
	if !apierrors.IsNotFound(err) {
		t.Fatalf("delete did not finish: %v", err)
	}
	if len(h.inventory.entries) != 0 || len(h.bundle.entries) != 0 {
		t.Fatal("cleanup incomplete")
	}
	s := h.control.states[string(m.UID)]
	if !s.Tombstone {
		t.Fatal("no durable tombstone")
	}
	_, err = h.control.Observe(context.Background(), Desired{CRUID: string(m.UID), Generation: m.Generation + 1})
	if err == nil {
		t.Fatal("tombstone resurrected")
	}
}
func TestUIDPreconditionDoesNotDeleteReplacement(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	entries, _ := h.inventory.List(context.Background(), string(h.m.UID), "")
	e := entries[0]
	obj := &unstructured.Unstructured{}
	obj.SetAPIVersion(e.Ref.APIVersion)
	obj.SetKind(e.Ref.Kind)
	key := client.ObjectKey{Namespace: e.Ref.Namespace, Name: e.Ref.Name}
	if err := h.c.Get(context.Background(), key, obj); err != nil {
		t.Fatal(err)
	}
	if err := h.c.Delete(context.Background(), obj); err != nil {
		t.Fatal(err)
	}
	obj.SetResourceVersion("")
	obj.SetUID(types.UID(uuid.NewString()))
	// Bypass test create counter, replacement is an external actor.
	h.inventory.beforeCreate++
	if err := h.c.Create(context.Background(), obj); err != nil {
		t.Fatal(err)
	}
	if err := (Resources{Client: h.c, Reader: h.c, Inventory: h.inventory}).Delete(context.Background(), e); err != ErrOwnership {
		t.Fatal("replacement was not protected", err)
	}
	if err := h.c.Get(context.Background(), key, obj); err != nil {
		t.Fatal("replacement deleted")
	}
}
func TestStaleGenerationRejectedBeforeSideEffects(t *testing.T) {
	h := newHarness(t)
	h.run()
	stale := h.current()
	h.change(func(m *api.ModelRelease) { m.Spec.Source.ExternalAPI.UpstreamModel = "new" })
	if err := h.r.fresh(context.Background(), stale); err != ErrConflict {
		t.Fatal("stale generation accepted")
	}
	h.run()
	s := h.control.states[string(h.m.UID)]
	old := s
	old.Generation--
	old.Fence--
	if err := h.control.Apply(context.Background(), command(old, "Activate", old.Candidate)); err != ErrConflict {
		t.Fatal("late command accepted")
	}
}
func TestSecretVersionChangesRevisionWithoutGenerationChange(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	old := h.current()
	h.resolver.version = "2"
	h.run()
	now := h.current()
	if now.Generation != old.Generation || *now.Status.DesiredRevision == *old.Status.DesiredRevision || *now.Status.PublicationID == *old.Status.PublicationID {
		t.Fatal("Secret metadata rotation ignored")
	}
}
func TestAliasConflictsAcrossNamespaces(t *testing.T) {
	c := newControl()
	d := Desired{CRUID: uuid.NewString(), Alias: "same", Gateway: api.Ref{Name: "gateway"}, Namespace: "one", Generation: 1}
	if _, err := c.Observe(context.Background(), d); err != nil {
		t.Fatal(err)
	}
	d.CRUID = uuid.NewString()
	d.Namespace = "two"
	if _, err := c.Observe(context.Background(), d); err != ErrConflict {
		t.Fatal("alias not unique across namespaces")
	}
}
func TestObjectDriftAndCollisionAreNotAdopted(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	entries, _ := h.inventory.List(context.Background(), string(h.m.UID), "")
	e := entries[0]
	o := &unstructured.Unstructured{}
	o.SetAPIVersion(e.Ref.APIVersion)
	o.SetKind(e.Ref.Kind)
	if err := h.c.Get(context.Background(), client.ObjectKey{Namespace: e.Ref.Namespace, Name: e.Ref.Name}, o); err != nil {
		t.Fatal(err)
	}
	a := o.GetAnnotations()
	a[OwnerAnnotation] = "another-owner"
	o.SetAnnotations(a)
	if err := h.c.Update(context.Background(), o); err != nil {
		t.Fatal(err)
	}
	h.run()
	ready(t, h.current(), false)
	if !h.control.states[string(h.m.UID)].AdmissionClosed {
		t.Fatal("detected active drift did not close durable admission")
	}
	if err := h.c.Get(context.Background(), client.ObjectKeyFromObject(o), o); err != nil {
		t.Fatal(err)
	}
	if o.GetAnnotations()[OwnerAnnotation] != "another-owner" {
		t.Fatal("object was adopted")
	}
}

func TestPendingInventoryCreateACKLossRecovery(t *testing.T) {
	for _, cleanup := range []bool{false, true} {
		t.Run(map[bool]string{false: "reconcile", true: "delete"}[cleanup], func(t *testing.T) {
			h := newHarness(t)
			h.run()
			m := h.current()
			res, _ := h.resolver.Resolve(context.Background(), m)
			b := Binding{PublicationID: uuid.NewString(), Revision: Revision(m.Spec, res), Generation: m.Generation, Epoch: 1}
			plan, err := Compile(m, res, b)
			if err != nil {
				t.Fatal(err)
			}
			p := plan.Objects[0]
			e := Entry{Owner: string(m.UID), Publication: b.PublicationID, Ref: ref(p.Object, b.PublicationID), Digest: p.Digest}
			if err = h.inventory.Intent(context.Background(), e); err != nil {
				t.Fatal(err)
			}
			if err = h.c.Create(context.Background(), p.Object.DeepCopy()); err != nil {
				t.Fatal(err)
			}
			// Simulated process death after create committed but before actual UID bind.
			resources := Resources{Client: h.c, Reader: h.c, Inventory: h.inventory}
			if cleanup {
				if err = resources.Delete(context.Background(), e); err != nil {
					t.Fatal(err)
				}
				if len(h.inventory.entries) != 0 {
					t.Fatal("pending intent not cleaned")
				}
			} else {
				if err = resources.Ensure(context.Background(), string(m.UID), b.PublicationID, p); err != nil {
					t.Fatal(err)
				}
				entries, _ := h.inventory.List(context.Background(), string(m.UID), b.PublicationID)
				if len(entries) != 1 || entries[0].Ref.UID == "" || h.creates != 1 {
					t.Fatal("create recovery duplicated or failed binding")
				}
			}
		})
	}
}

func TestRecreateWaitsBeforePreparingReplacement(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	h.control.safe = false
	h.change(func(m *api.ModelRelease) {
		m.Spec.Lifecycle.Strategy = "Recreate"
		m.Spec.Source.ExternalAPI.UpstreamModel = "replacement"
	})
	h.run()
	if h.creates != 2 || !h.control.states[string(h.m.UID)].AdmissionClosed {
		t.Fatal("replacement prepared before old drain")
	}
	h.control.safe = true
	h.run()
	ready(t, h.current(), true)
}
func TestCleanupNeverDeletesUserOrSharedResources(t *testing.T) {
	h := newHarness(t)
	for _, kind := range []string{"Secret", "PersistentVolumeClaim", "McpBridge", "CustomResourceDefinition"} {
		e := Entry{Owner: string(h.m.UID), Publication: uuid.NewString(), Ref: api.ResourceRef{APIVersion: "v1", Kind: kind, Namespace: h.m.Namespace, Name: "user-resource", Ownership: "exclusive"}}
		if err := (Resources{Client: h.c, Reader: h.c, Inventory: h.inventory}).Delete(context.Background(), e); err != ErrOwnership {
			t.Fatalf("%s became cleanup target: %v", kind, err)
		}
	}
}
