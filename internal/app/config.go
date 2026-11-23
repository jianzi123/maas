// Package app assembles the normal MySQL-backed product process. Controlled
// models/file stores are never selected by this entrypoint.
package app

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/url"
	"os"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/protocol"
)

var ErrConfig = errors.New("invalid_product_configuration")

type MySQLConfig struct {
	RuntimeDSNFile   string `json:"runtime_dsn_file"`
	MigrationDSNFile string `json:"migration_dsn_file"`
}
type AuthConfig struct {
	AdminID           string `json:"admin_id"`
	Username          string `json:"username"`
	PasswordFile      string `json:"password_file"`
	SessionTTLSeconds int    `json:"session_ttl_seconds"`
	SecureCookie      bool   `json:"secure_cookie"`
}
type Secrets struct {
	PepperFile    string `json:"key_pepper_file"`
	CursorKeyFile string `json:"cursor_key_file"`
}
type AgentConfig struct {
	Limits        a.ARLimits `json:"limits"`
	InputBytes    int        `json:"input_bytes"`
	Events        int        `json:"max_events"`
	ApprovalTTLMS int        `json:"approval_ttl_ms"`
	Concurrency   int        `json:"concurrency"`
}
type ModelConfig struct {
	Alias           string `json:"alias"`
	PublicationID   string `json:"publication_id"`
	PlatformKeyFile string `json:"platform_key_file"`
	Protocol        string `json:"protocol"`
	TimeoutMS       int    `json:"timeout_ms"`
}
type GatewayConfig struct {
	Endpoint         string `json:"endpoint"`
	CAFile           string `json:"ca_file"`
	CertificateFile  string `json:"client_cert_file"`
	PrivateKeyFile   string `json:"client_key_file"`
	AdmissionKeyFile string `json:"admission_key_file"`
	Kid              string `json:"signer_kid"`
	Owner            string `json:"signer_owner"`
	RateRevision     string `json:"rate_revision"`
	DialTimeoutMS    int    `json:"dial_timeout_ms"`
	HeaderTimeoutMS  int    `json:"header_timeout_ms"`
	TicketTTLMS      int    `json:"ticket_ttl_ms"`
	MaxResponseBytes int64  `json:"max_response_bytes"`
	MaxEventBytes    int    `json:"max_event_bytes"`
}
type Config struct {
	Offline      OfflineConfig    `json:"offline_controlled"`
	Management   ManagementConfig `json:"management"`
	Ledger       LedgerConfig     `json:"ledger"`
	Listen       string           `json:"listen"`
	Origin       string           `json:"origin"`
	Cluster      string           `json:"cluster_id"`
	StaticDir    string           `json:"static_dir"`
	ContractFile string           `json:"contract_file"`
	MySQL        MySQLConfig      `json:"mysql"`
	Auth         AuthConfig       `json:"auth"`
	Secrets      Secrets          `json:"secrets"`
	Agent        AgentConfig      `json:"agent"`
	Models       []ModelConfig    `json:"models"`
	Gateway      GatewayConfig    `json:"gateway"`
}

func LoadConfig(name string) (Config, error) {
	var c Config
	b, e := os.ReadFile(name)
	if e != nil || len(b) > 1<<20 {
		return c, ErrConfig
	}
	b, e = protocol.Canonical(b)
	if e != nil {
		return c, ErrConfig
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if d.Decode(&c) != nil || d.Decode(new(any)) != io.EOF {
		return c, ErrConfig
	}
	return c, c.Validate()
}
func (c Config) Validate() error {
	if c.Offline.Enabled && (len(c.Models) > 0 || c.Management.Enabled || c.Offline.StepDelayMS < 0 || c.Offline.StepDelayMS > 10000) {
		return ErrConfig
	}
	if c.Management.Enabled && (c.Management.HistoryDSNFile == "" || c.Management.PayloadDSNFile == "" || c.Management.OperationsDSNFile == "" || c.Management.PublisherDSNFile == "" || c.Management.KubeconfigFile == "" || c.Management.RegistryFile == "" || c.Management.ScopeID == "" || len(c.Management.Namespaces) == 0 || len(c.Management.Domains) == 0) {
		return ErrConfig
	}
	if len(c.Models) > 100 || len(c.Auth.Username) > 128 {
		return ErrConfig
	}
	if c.Ledger.Revision == "" || c.Ledger.Epoch < 1 || c.Ledger.WindowMS < 1 || c.Ledger.GlobalLimit < 1 || c.Ledger.KeyLimit < 1 || c.Ledger.Slots < 1 || c.Ledger.Slots > 10000 {
		return ErrConfig
	}
	_, port, e := net.SplitHostPort(c.Listen)
	if e != nil || port == "" {
		return ErrConfig
	}
	u, e := url.Parse(c.Origin)
	if e != nil || u.User != nil || u.Host == "" || u.Path != "" || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "http" && u.Scheme != "https") {
		return ErrConfig
	}
	if u.Scheme == "https" && !c.Auth.SecureCookie {
		return ErrConfig
	}
	if _, e = uuid.Parse(c.Auth.AdminID); e != nil {
		return ErrConfig
	}
	if c.Cluster == "" || c.MySQL.RuntimeDSNFile == "" || c.MySQL.MigrationDSNFile == "" || c.Auth.Username == "" || c.Auth.PasswordFile == "" || c.Auth.SessionTTLSeconds < 60 || c.Auth.SessionTTLSeconds > 86400 || c.Secrets.PepperFile == "" || c.Secrets.CursorKeyFile == "" || c.ContractFile == "" || c.Agent.Concurrency < 1 || c.Agent.Concurrency > 128 || c.Agent.InputBytes < 1024 || c.Agent.InputBytes > 1<<20 || c.Agent.Events < 64 || c.Agent.Events > 100000 || c.Agent.ApprovalTTLMS < 1 {
		return ErrConfig
	}
	seen := map[string]bool{}
	for _, m := range c.Models {
		if m.Alias == "" || seen[m.Alias] || m.PlatformKeyFile == "" || m.TimeoutMS < 1 || m.TimeoutMS > int((24*time.Hour).Milliseconds()) || (m.Protocol != "text-v1" && m.Protocol != "tools-v1") {
			return ErrConfig
		}
		if _, e = uuid.Parse(m.PublicationID); e != nil {
			return ErrConfig
		}
		seen[m.Alias] = true
	}
	return nil
}
func secret(name string, min, max int) ([]byte, error) {
	f, e := os.Open(name)
	if e != nil {
		return nil, ErrConfig
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, int64(max+1)))
	b = bytes.TrimSpace(b)
	if e != nil || len(b) < min || len(b) > max {
		return nil, ErrConfig
	}
	return b, nil
}
