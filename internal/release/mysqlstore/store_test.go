package mysqlstore

import (
	"database/sql"
	"errors"
	"strings"
	"testing"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
)

func desired() release.Desired {
	return release.Desired{CRUID: uuid.NewString(), Namespace: "models", Name: "model", Alias: "model", Gateway: api.Ref{Name: "private", Revision: "approved-1"}, Generation: 1, Revision: strings.Repeat("a", 64)}
}
func TestInputAndErrorBoundary(t *testing.T) {
	if _, err := New(nil, "test", nil); err != release.ErrDependencyMissing {
		t.Fatal(err)
	}
	for _, cluster := range []string{"", "invalid/cluster", "汉字"} {
		if _, err := New(new(sql.DB), cluster, nil); err == nil {
			t.Fatal("invalid cluster")
		}
	}
	d := desired()
	if err := validateDesired(d); err != nil {
		t.Fatal(err)
	}
	d.Generation = maxCounter + 1
	if validateDesired(d) == nil {
		t.Fatal("counter overflow")
	}
	if publicError(errors.New("SENSITIVE database connection details")) != ErrUnavailable {
		t.Fatal("raw error escaped")
	}
	for _, number := range []uint16{1062, 1205, 1213, 3572} {
		if publicError(&mysql.MySQLError{Number: number, Message: "SENSITIVE"}) != release.ErrConflict {
			t.Fatal(number)
		}
	}
}
func TestInventoryIdentityAndAllowlist(t *testing.T) {
	d := desired()
	p := uuid.NewString()
	e := release.Entry{Owner: d.CRUID, Publication: p, Digest: d.Revision, Ref: api.ResourceRef{APIVersion: "v1", Kind: "ConfigMap", Namespace: d.Namespace, Name: "plan", Ownership: "exclusive", PublicationID: &p}}
	if err := validateEntry(e); err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"Secret", "PersistentVolumeClaim", "McpBridge"} {
		bad := e
		bad.Ref.Kind = kind
		if validateEntry(bad) == nil {
			t.Fatal("user/shared resource accepted", kind)
		}
	}
	bad := e
	bad.Owner = uuid.NewString()
	if identity(e, bad) {
		t.Fatal("different UID adopted")
	}
	bad = e
	bad.Publication = uuid.NewString()
	if identity(e, bad) {
		t.Fatal("different publication adopted")
	}
	s, _ := New(new(sql.DB), "one", nil)
	other, _ := New(new(sql.DB), "two", nil)
	if s.resourceKey(e) == other.resourceKey(e) {
		t.Fatal("cluster not in resource identity")
	}
}
