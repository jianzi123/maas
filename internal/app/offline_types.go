package app

// OfflineConfig is opt-in and mutually exclusive with real model entries. It
// selects a deterministic model plus scoped synthetic gateway/rate witnesses;
// application state and original admission/settlement remain real MySQL.
type OfflineConfig struct {
	Enabled         bool `json:"enabled"`
	RequireApproval bool `json:"require_approval"`
	StepDelayMS     int  `json:"step_delay_ms"`
}

type ManagementConfig struct {
	Enabled           bool     `json:"enabled"`
	HistoryDSNFile    string   `json:"history_dsn_file"`
	PayloadDSNFile    string   `json:"payload_dsn_file"`
	OperationsDSNFile string   `json:"operations_dsn_file"`
	PublisherDSNFile  string   `json:"publisher_dsn_file"`
	KubeconfigFile    string   `json:"kubeconfig_file"`
	RegistryFile      string   `json:"registry_file"`
	Namespaces        []string `json:"namespaces"`
	Domains           []string `json:"authorization_domains"`
	ScopeID           string   `json:"scope_id"`
}
