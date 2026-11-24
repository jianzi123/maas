package app

import (
	"context"
	"strings"
	"testing"
)

func TestProductManagementNeverFallsBackToCoreIdentity(t *testing.T) {
	c, _ := productFixture(t)
	if e := Migrate(context.Background(), c); e != nil {
		t.Fatal(e)
	}
	c.Management = ManagementConfig{Enabled: true, HistoryDSNFile: c.MySQL.RuntimeDSNFile, PayloadDSNFile: c.MySQL.RuntimeDSNFile, OperationsDSNFile: c.MySQL.RuntimeDSNFile, PublisherDSNFile: c.MySQL.RuntimeDSNFile, KubeconfigFile: "not-consumed-before-identity-check", RegistryFile: "not-consumed-before-identity-check", Namespaces: []string{"scope"}, Domains: []string{"domain"}, ScopeID: "test-scope"}
	r, e := Open(context.Background(), c)
	if e == nil {
		r.Close()
		t.Fatal("core identity substituted for management")
	}
	if !strings.Contains(e.Error(), "identity_must_be_independent") {
		t.Fatal("unexpected rejection", e)
	}
}
func TestProductManagementRequiresExplicitConfiguration(t *testing.T) {
	c := Config{}
	c.Management.Enabled = true
	if c.Validate() == nil {
		t.Fatal("management silently configured")
	}
}
