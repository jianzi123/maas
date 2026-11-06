// Package v1alpha1 contains the review API. Group is a reserved placeholder,
// not an assigned product domain. Change all generated artifacts together.
package v1alpha1

import (
	"encoding/json"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

const Group = "serving.maas.example"

var GroupVersion = schema.GroupVersion{Group: Group, Version: "v1alpha1"}

func AddToScheme(s *runtime.Scheme) error {
	s.AddKnownTypes(GroupVersion, &ModelRelease{}, &ModelReleaseList{})
	metav1.AddToGroupVersion(s, GroupVersion)
	return nil
}

type Ref struct {
	Name     string `json:"name"`
	Revision string `json:"revision"`
}
type SecretKeyRef struct {
	Name string `json:"name"`
	Key  string `json:"key"`
}
type Weights struct {
	PVCName       string `json:"pvcName"`
	Path          string `json:"path"`
	SHA256        string `json:"sha256"`
	ModelRevision string `json:"modelRevision"`
}
type SelfHosted struct {
	Engine                string  `json:"engine"`
	Workload              string  `json:"workload"`
	Weights               Weights `json:"weights"`
	RuntimeProfileRef     Ref     `json:"runtimeProfileRef"`
	PlacementProfileRef   Ref     `json:"placementProfileRef"`
	Image                 string  `json:"image"`
	Groups                int     `json:"groups"`
	PodsPerGroup          int     `json:"podsPerGroup"`
	GPUsPerPod            int     `json:"gpusPerPod"`
	GPUResourceName       string  `json:"gpuResourceName"`
	CPUPerPod             string  `json:"cpuPerPod"`
	MemoryPerPod          string  `json:"memoryPerPod"`
	TensorParallelSize    int     `json:"tensorParallelSize"`
	PipelineParallelSize  int     `json:"pipelineParallelSize"`
	StartupTimeoutSeconds int     `json:"startupTimeoutSeconds"`
}
type ExternalAPI struct {
	Provider            string       `json:"provider"`
	EndpointRef         Ref          `json:"endpointRef"`
	UpstreamModel       string       `json:"upstreamModel"`
	Protocol            string       `json:"protocol"`
	CredentialSecretRef SecretKeyRef `json:"credentialSecretRef"`
}
type Source struct {
	Type        string       `json:"type"`
	SelfHosted  *SelfHosted  `json:"selfHosted,omitempty"`
	ExternalAPI *ExternalAPI `json:"externalAPI,omitempty"`
}
type BusinessRefs struct {
	CapabilityProfileRef Ref `json:"capabilityProfileRef"`
	PricePolicyRef       Ref `json:"pricePolicyRef"`
	IntakePolicyRef      Ref `json:"intakePolicyRef"`
}
type Lifecycle struct {
	DesiredState            string `json:"desiredState"`
	Strategy                string `json:"strategy"`
	DrainTimeoutSeconds     int    `json:"drainTimeoutSeconds"`
	ProgressDeadlineSeconds int    `json:"progressDeadlineSeconds"`
	RetainedRevisions       int    `json:"retainedRevisions"`
	RetainUserData          bool   `json:"retainUserData"`
}
type Spec struct {
	ModelAlias   string       `json:"modelAlias"`
	Source       Source       `json:"source"`
	GatewayRef   Ref          `json:"gatewayRef"`
	BusinessRefs BusinessRefs `json:"businessRefs"`
	Lifecycle    Lifecycle    `json:"lifecycle"`
}
type ResourceRef struct {
	APIVersion    string  `json:"apiVersion"`
	Kind          string  `json:"kind"`
	Namespace     string  `json:"namespace"`
	Name          string  `json:"name"`
	UID           string  `json:"uid"`
	Ownership     string  `json:"ownership"`
	PublicationID *string `json:"publication_id"`
}
type Operation struct {
	ID                  string      `json:"id"`
	Action              string      `json:"action"`
	State               string      `json:"state"`
	Namespace           string      `json:"namespace"`
	Name                string      `json:"name"`
	CRUID               *string     `json:"cr_uid"`
	RequestedGeneration *int64      `json:"requested_generation"`
	PublicationID       *string     `json:"publication_id"`
	CreatedAt           metav1.Time `json:"created_at"`
	UpdatedAt           metav1.Time `json:"updated_at"`
	Reason              *string     `json:"reason"`
	Message             string      `json:"message"`
}
type Status struct {
	ObservedGeneration int64              `json:"observedGeneration"`
	Phase              string             `json:"phase"`
	DesiredRevision    *string            `json:"desiredRevision"`
	ActiveRevision     *string            `json:"activeRevision"`
	ActiveGeneration   *int64             `json:"activeGeneration"`
	PublicationID      *string            `json:"publication_id"`
	ActivationEpoch    int64              `json:"activation_epoch"`
	AvailableGroups    int                `json:"availableGroups"`
	Conditions         []metav1.Condition `json:"conditions"`
	Resources          []ResourceRef      `json:"resources"`
	Operation          *Operation         `json:"operation"`
}
type ModelRelease struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`
	Spec              Spec   `json:"spec"`
	Status            Status `json:"status,omitempty"`
}
type ModelReleaseList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ModelRelease `json:"items"`
}

func (r *ModelRelease) DeepCopy() *ModelRelease {
	if r == nil {
		return nil
	}
	out := new(ModelRelease)
	// These API structs contain only JSON types; encoding cannot fail.
	data, _ := json.Marshal(r)
	_ = json.Unmarshal(data, out)
	return out
}
func (r *ModelRelease) DeepCopyObject() runtime.Object { return r.DeepCopy() }
func (r *ModelReleaseList) DeepCopyObject() runtime.Object {
	if r == nil {
		return (*ModelReleaseList)(nil)
	}
	out := new(ModelReleaseList)
	data, _ := json.Marshal(r)
	_ = json.Unmarshal(data, out)
	return out
}
