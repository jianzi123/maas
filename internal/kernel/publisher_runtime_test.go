package kernel

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

// This test covers new factory wiring, not a repeat of R1-R3/ACK-loss review.
func TestPublisherRuntimeWiring(t *testing.T) {
	f := setup(t, 1)
	ctx := context.Background()
	for _, dsn := range []string{"", "invalid-secret-dsn", f.config.FormatDSN()} {
		if _, err := mysqlstore.OpenPublisher(ctx, dsn, "controlled-test", f.core); err == nil || strings.Contains(err.Error(), "secret-dsn") {
			t.Fatal("missing/malformed/root connection accepted or disclosed")
		}
	}
	for _, name := range []string{"release-permissions.sql", "kernel-permissions.sql"} {
		b, err := os.ReadFile("../../config/mysql/" + name)
		if err != nil {
			t.Fatal(err)
		}
		var lines []string
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(line), "--") {
				lines = append(lines, line)
			}
		}
		for _, q := range strings.Split(strings.Join(lines, "\n"), ";") {
			if !strings.Contains(q, "maas_release_publisher") {
				continue
			}
			q = strings.ReplaceAll(q, "__MAAS_DATABASE__", "`"+f.config.DBName+"`")
			if _, err = f.db.Exec(q); err != nil {
				t.Fatal(err)
			}
		}
	}
	t.Cleanup(func() { f.db.Exec("DROP ROLE maas_release_publisher") })
	user := "wire_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	if _, err := f.db.Exec("CREATE USER '" + user + "'@'localhost'"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { f.db.Exec("DROP USER '" + user + "'@'localhost'") })
	f.db.Exec("GRANT maas_release_publisher TO '" + user + "'@'localhost'")
	cfg := f.config.Clone()
	cfg.User = user
	cfg.Passwd = ""
	if _, err := mysqlstore.OpenPublisher(ctx, cfg.FormatDSN(), "controlled-test", f.core); err == nil {
		t.Fatal("inactive default role accepted")
	}
	if _, err := f.db.Exec("SET DEFAULT ROLE maas_release_publisher TO '" + user + "'@'localhost'"); err != nil {
		t.Fatal(err)
	}
	if _, err := mysqlstore.OpenPublisher(ctx, cfg.FormatDSN(), "controlled-test", nil); err == nil {
		t.Fatal("missing evidence port accepted")
	}
	runtime, err := mysqlstore.OpenPublisher(ctx, cfg.FormatDSN(), "controlled-test", f.core)
	if err != nil {
		t.Fatal(err)
	}
	defer runtime.Close()
	pub := runtime.Store
	for _, q := range []string{"UPDATE release_management_operations SET action='Delete'", "UPDATE release_management_operations SET spec_sha256=REPEAT('0',64)", "UPDATE release_management_operations SET expected_rv='bad'", "UPDATE platform_keys SET revoked=FALSE", "UPDATE budget_windows SET uncertainty_held=0", "DELETE FROM usage_events", "CREATE TABLE forbidden_runtime(id INT)"} {
		_, e := runtime.DB.Exec(q)
		var denied *mysql.MySQLError
		if !errors.As(e, &denied) || (denied.Number != 1142 && denied.Number != 1143) {
			t.Fatal("unexpected permission result", e)
		}
		t.Log("denied", q, "mysql", denied.Number)
	}
	st, err := pub.Read(ctx, f.desired.CRUID)
	if err != nil {
		t.Fatal(err)
	}
	active := st.Active.PublicationID
	close := release.Command{ID: uuid.NewString(), Action: "CloseAdmission", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Revision: st.Revision, EvidenceRefs: []string{}}
	if _, err = f.db.Exec("REVOKE UPDATE(state) ON `" + f.config.DBName + "`.release_management_operations FROM maas_release_publisher"); err != nil {
		t.Fatal(err)
	}
	if pub.Apply(ctx, close) == nil {
		t.Fatal("factory omitted atomic completion hook")
	}
	after, err := f.gate.Read(ctx, st.CRUID)
	if err != nil || after.AdmissionClosed {
		t.Fatal("permission failure half-committed gate")
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM release_operations WHERE command_id=?", 0, close.ID)
	if _, err = f.db.Exec("GRANT UPDATE(state) ON `" + f.config.DBName + "`.release_management_operations TO maas_release_publisher"); err != nil {
		t.Fatal(err)
	}
	if err = pub.Apply(ctx, close); err != nil {
		t.Fatal(err)
	}
	d := f.desired
	d.Generation++
	d.Paused = true
	op := uuid.NewString()
	if _, err = f.db.Exec(`INSERT INTO release_management_operations(cluster_id,operation_id,scope_id,namespace,name,action,desired_state,cr_uid,expected_rv,spec_sha256,state,acknowledged,requested_generation) VALUES('controlled-test',?,'runtime',?,?,'Pause','Paused',?,'1',REPEAT('0',64),'Running',TRUE,?)`, op, d.Namespace, d.Name, d.CRUID, d.Generation); err != nil {
		t.Fatal(err)
	}
	st, err = pub.Observe(ctx, d)
	if err != nil {
		t.Fatal(err)
	}
	active = st.Active.PublicationID
	if err = pub.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "RecordCleanup", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Revision: st.Revision, EvidenceRefs: []string{}}); err != nil {
		t.Fatal(err)
	}
	var state string
	if f.db.QueryRow("SELECT state FROM release_management_operations WHERE operation_id=?", op).Scan(&state) != nil || state != "Succeeded" {
		t.Fatal("original operation not completed", state)
	}
	t.Log("factory/default role, close, rollback-on-permission-failure, cleanup and original Pause operation passed; R3 Activate/ACK evidence remains ac94")
}
