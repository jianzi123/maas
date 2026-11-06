package mysqlstore

// These fixtures run only against scripts/test-mysql.sh's disposable Unix-socket
// server. The core tables and evidence producer below are TEST ONLY, not another
// production request/slot/budget kernel or a production Ready source.
import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
)

type testDB struct {
	db, admin *sql.DB
	config    *mysql.Config
	name      string
}

func databaseFixture(t *testing.T) *testDB {
	t.Helper()
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("MySQL 8.4 test dependency not provided; use scripts/test-mysql.sh")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("requires the explicitly disposable test server")
	}
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = 3 * time.Second
	cfg.ReadTimeout = 5 * time.Second
	cfg.WriteTimeout = 5 * time.Second
	admin, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		t.Fatal("open disposable database")
	}
	name := "maas_release_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, err = admin.Exec("CREATE DATABASE `" + name + "`"); err != nil {
		t.Fatal(err)
	}
	cfg.DBName = name
	db, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(10)
	f := &testDB{db: db, admin: admin, config: cfg, name: name}
	t.Cleanup(func() {
		db.Close()
		_, err := admin.Exec("DROP DATABASE `" + name + "`")
		if err != nil {
			t.Error("test schema cleanup", err)
		}
		admin.Close()
	})
	if err = Migrate(context.Background(), db); err != nil {
		t.Fatal("migration", err)
	}
	if err = Migrate(context.Background(), db); err != nil {
		t.Fatal("idempotent migration", err)
	}
	for _, ddl := range []string{
		`CREATE TABLE test_core_capacity(id INT PRIMARY KEY) ENGINE=InnoDB`,
		`INSERT INTO test_core_capacity VALUES(1)`,
		`CREATE TABLE test_core_requests(id INT PRIMARY KEY,publication_id CHAR(36),state VARCHAR(20)) ENGINE=InnoDB`,
		`CREATE TABLE test_core_slots(id INT PRIMARY KEY,publication_id CHAR(36),state VARCHAR(20),allocation_fence BIGINT) ENGINE=InnoDB`,
		`CREATE TABLE test_core_unknown_hold(id INT PRIMARY KEY,amount BIGINT) ENGINE=InnoDB`,
		`INSERT INTO test_core_unknown_hold VALUES(1,123456)`,
	} {
		if _, err = db.Exec(ddl); err != nil {
			t.Fatal(err)
		}
	}
	return f
}

type coreFixture struct{ expired, unready, mismatched bool }

func (k *coreFixture) LockCapacity(ctx context.Context, tx *sql.Tx) error {
	var id int
	return tx.QueryRowContext(ctx, "SELECT id FROM test_core_capacity WHERE id=1 FOR SHARE NOWAIT").Scan(&id)
}
func (k *coreFixture) PublicationEvidence(ctx context.Context, tx *sql.Tx, p Publication) (Evidence, error) {
	now, err := dbNow(ctx, tx)
	if err != nil {
		return Evidence{}, err
	}
	until := now.Add(time.Minute)
	if k.expired {
		until = now.Add(-time.Second)
	}
	e := Evidence{Binding: p.Binding, CRUID: p.CRUID, FreshUntil: until, RuntimeReady: true, GatewayApplied: true, AccountingReady: !k.unready, ValidationPassed: true, Refs: []string{"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}}
	if k.mismatched {
		e.Binding.Epoch++
	}
	return e, nil
}
func (k *coreFixture) DrainEvidence(ctx context.Context, tx *sql.Tx, uid string, pubs []Publication) (DrainEvidence, error) {
	now, err := dbNow(ctx, tx)
	if err != nil {
		return DrainEvidence{}, err
	}
	out := DrainEvidence{CRUID: uid, Verified: true, FreshUntil: now.Add(time.Minute), Publications: []string{}}
	for _, p := range pubs {
		out.Publications = append(out.Publications, p.PublicationID)
		var count int64
		if err = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM test_core_requests WHERE publication_id=? AND state='in_progress'`, p.PublicationID).Scan(&count); err != nil {
			return out, err
		}
		out.InProgress += count
		for _, state := range []string{"HELD", "QUARANTINED"} {
			if err = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM test_core_slots WHERE publication_id=? AND state=?`, p.PublicationID, state).Scan(&count); err != nil {
				return out, err
			}
			if state == "HELD" {
				out.HeldSlots += count
			} else {
				out.QuarantinedSlots += count
			}
		}
	}
	return out, nil
}
func testStore(t *testing.T, db *sql.DB, k Kernel) *Store {
	t.Helper()
	s, err := New(db, "test-cluster", k)
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func observe(t *testing.T, s *Store, d release.Desired) release.State {
	t.Helper()
	v, err := s.Observe(context.Background(), d)
	if err != nil {
		t.Fatal(err)
	}
	return v
}
func cmd(s release.State, action string) *release.Command {
	c := &release.Command{ID: uuid.NewString(), Action: action, CRUID: s.CRUID, Generation: s.Generation, Fence: s.Fence, Revision: s.Revision, EvidenceRefs: append([]string{}, s.EvidenceRefs...)}
	if s.Active != nil {
		v := s.Active.PublicationID
		c.ExpectedActive = &v
	}
	if s.Candidate != nil {
		v := s.Candidate.PublicationID
		c.Target = &v
	}
	return c
}
func apply(t *testing.T, s *Store, c *release.Command) {
	t.Helper()
	if err := s.Apply(context.Background(), *c); err != nil {
		t.Fatal(err)
	}
}
func count(t *testing.T, db *sql.DB, q string, args ...any) int64 {
	t.Helper()
	var v int64
	if err := db.QueryRow(q, args...).Scan(&v); err != nil {
		t.Fatal(err)
	}
	return v
}

func TestMySQLRelease(t *testing.T) {
	if os.Getenv("MAAS_MYSQL_TEST_SOCKET") == "" {
		t.Skip("requires explicitly enabled disposable MySQL; see scripts/test-mysql.sh")
	}
	t.Run("idempotent_observe_restart_and_monotonic_epoch", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, nil)
		d := desired()
		a := observe(t, s, d)
		again := observe(t, s, d)
		if *a.Candidate != *again.Candidate || a.Fence != again.Fence || a.RuntimeReady {
			t.Fatal("non-idempotent or fake Ready")
		}
		d.Revision = strings.Repeat("b", 64)
		b := observe(t, s, d)
		if b.Candidate.PublicationID == a.Candidate.PublicationID || b.Candidate.Epoch <= a.Candidate.Epoch {
			t.Fatal("same-generation dependency rotation reused publication")
		}
		d.Generation++
		d.Revision = strings.Repeat("a", 64)
		rolled := observe(t, s, d)
		if rolled.Candidate.PublicationID == a.Candidate.PublicationID || rolled.Candidate.Epoch <= b.Candidate.Epoch {
			t.Fatal("rollback resurrected publication")
		}
		restarted := testStore(t, f.db, nil)
		recovered, err := restarted.Read(context.Background(), d.CRUID)
		if err != nil || *recovered.Candidate != *rolled.Candidate {
			t.Fatal("restart recovery", err)
		}
		d.Generation--
		if _, err = s.Observe(context.Background(), d); err != release.ErrConflict {
			t.Fatal("stale generation", err)
		}
	})
	t.Run("activation_CAS_exact_replay_and_closed_publication", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, &coreFixture{})
		d := desired()
		a := observe(t, s, d)
		activation := cmd(a, "Activate")
		apply(t, s, activation)
		apply(t, s, activation)
		conflicting := *activation
		conflicting.Revision = strings.Repeat("c", 64)
		if err := s.Apply(context.Background(), conflicting); err != release.ErrConflict {
			t.Fatal("same command ID different hash", err)
		}
		d.Generation++
		d.Revision = strings.Repeat("b", 64)
		b := observe(t, s, d)
		stale := *activation
		stale.ID = uuid.NewString()
		if err := s.Apply(context.Background(), stale); err != release.ErrConflict {
			t.Fatal("stale fence accepted", err)
		}
		apply(t, s, cmd(b, "Activate"))
		newer, err := s.Read(context.Background(), d.CRUID)
		if err != nil {
			t.Fatal(err)
		}
		// Replaying the old recorded command cannot restore its old active binding.
		apply(t, s, activation)
		after, _ := s.Read(context.Background(), d.CRUID)
		if *after.Active != *newer.Active {
			t.Fatal("replay changed binding")
		}
		closeCmd := cmd(after, "CloseAdmission")
		closeCmd.Target = nil
		apply(t, s, closeCmd)
		next := observe(t, s, d)
		if next.Candidate.PublicationID == after.Active.PublicationID || next.Candidate.Epoch <= after.Active.Epoch {
			t.Fatal("closed publication resurrected")
		}
		if count(t, f.db, `SELECT COUNT(*) FROM publications WHERE activated=TRUE`) != 2 {
			t.Fatal("duplicate activation")
		}
	})
	t.Run("fail_closed_missing_expired_mismatched_or_unready_evidence", func(t *testing.T) {
		f := databaseFixture(t)
		d := desired()
		missing := testStore(t, f.db, nil)
		state := observe(t, missing, d)
		if err := missing.Apply(context.Background(), *cmd(state, "Activate")); err != release.ErrDependencyMissing {
			t.Fatal("missing core allowed activation", err)
		}
		for _, k := range []*coreFixture{{expired: true}, {unready: true}, {mismatched: true}} {
			s := testStore(t, f.db, k)
			state = observe(t, s, d)
			if err := s.Apply(context.Background(), *cmd(state, "Activate")); err != release.ErrDependencyMissing {
				t.Fatal("invalid evidence allowed activation", err)
			}
		}
		if count(t, f.db, `SELECT COUNT(*) FROM publications WHERE activated=TRUE`) != 0 {
			t.Fatal("failed transaction committed")
		}
	})
	t.Run("tombstone_alias_reservation_and_UID_isolation", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, &coreFixture{})
		d := desired()
		a := observe(t, s, d)
		apply(t, s, cmd(a, "Activate"))
		other := d
		other.CRUID = uuid.NewString()
		other.Namespace = "other-namespace"
		if _, err := s.Observe(context.Background(), other); err != release.ErrConflict {
			t.Fatal("alias collision accepted", err)
		}
		d.Deleting = true
		closed := observe(t, s, d)
		if !closed.Tombstone || !closed.AdmissionClosed {
			t.Fatal("deletion not durable")
		}
		resurrect := d
		resurrect.Deleting = false
		resurrect.Generation++
		if _, err := s.Observe(context.Background(), resurrect); err != release.ErrConflict {
			t.Fatal("tombstone resurrected", err)
		}
		if _, err := s.Observe(context.Background(), other); err != release.ErrConflict {
			t.Fatal("alias released before cleanup")
		}
		cleanup := cmd(closed, "RecordCleanup")
		cleanup.Target = nil
		apply(t, s, cleanup)
		b := observe(t, s, other)
		if b.CRUID != other.CRUID {
			t.Fatal("new UID not isolated")
		}
		observe(t, s, d) // old deletion replay must not steal the new alias claim
		if count(t, f.db, `SELECT tombstone FROM release_links WHERE cr_uid=?`, d.CRUID) != 1 {
			t.Fatal("tombstone removed")
		}
	})
	t.Run("inventory_pending_UID_recovery_and_safe_slot_cleanup", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, &coreFixture{})
		d := desired()
		state := observe(t, s, d)
		pub := state.Candidate.PublicationID
		e := release.Entry{Owner: d.CRUID, Publication: pub, Digest: d.Revision, Ref: api.ResourceRef{APIVersion: "networking.k8s.io/v1", Kind: "Ingress", Namespace: "gateway", Name: "dedicated", Ownership: "exclusive", PublicationID: &pub}}
		if err := s.Intent(context.Background(), e); err != nil {
			t.Fatal(err)
		}
		if err := s.Intent(context.Background(), e); err != nil {
			t.Fatal(err)
		}
		restarted := testStore(t, f.db, &coreFixture{})
		entries, err := restarted.List(context.Background(), d.CRUID, pub)
		if err != nil || len(entries) != 1 || entries[0].Ref.UID != "" {
			t.Fatal("pending inventory lost", err)
		}
		e.Ref.UID = uuid.NewString()
		if err = s.Bind(context.Background(), e); err != nil {
			t.Fatal(err)
		}
		replacement := e
		replacement.Ref.UID = uuid.NewString()
		if err = s.Bind(context.Background(), replacement); err != release.ErrOwnership {
			t.Fatal("different UID bound", err)
		}
		if err = s.Retire(context.Background(), e); err != release.ErrConflict {
			t.Fatal("candidate retired", err)
		}
		d.Generation++
		d.Paused = true
		observe(t, s, d)
		if _, err = f.db.Exec(`INSERT INTO test_core_slots VALUES(1,?,'HELD',7)`, pub); err != nil {
			t.Fatal(err)
		}
		for _, slotState := range []string{"HELD", "QUARANTINED"} {
			_, _ = f.db.Exec(`UPDATE test_core_slots SET state=? WHERE id=1`, slotState)
			if err = s.Retire(context.Background(), e); err != release.ErrConflict {
				t.Fatal("unsafe slot retired", slotState, err)
			}
		}
		_, _ = f.db.Exec(`UPDATE test_core_slots SET state='FREE' WHERE id=1`)
		_, _ = f.db.Exec(`INSERT INTO test_core_requests VALUES(1,?,'in_progress')`, pub)
		if err = s.Retire(context.Background(), e); err != release.ErrConflict {
			t.Fatal("transport still active", err)
		}
		_, _ = f.db.Exec(`UPDATE test_core_requests SET state='cancelled' WHERE id=1`)
		if err = s.Retire(context.Background(), replacement); err != release.ErrOwnership {
			t.Fatal("replacement UID retired", err)
		}
		if err = s.Retire(context.Background(), e); err != nil {
			t.Fatal(err)
		}
		if err = s.Bind(context.Background(), e); err != release.ErrConflict {
			t.Fatal("retiring resource reattached", err)
		}
		if err = s.Removed(context.Background(), e); err != nil {
			t.Fatal(err)
		}
		if err = s.Removed(context.Background(), e); err != nil {
			t.Fatal(err)
		}
		if count(t, f.db, `SELECT amount FROM test_core_unknown_hold WHERE id=1`) != 123456 {
			t.Fatal("cleanup changed financial hold")
		}
		if count(t, f.db, `SELECT allocation_fence FROM test_core_slots WHERE id=1`) != 7 {
			t.Fatal("inventory changed slot binding")
		}
		if count(t, f.db, `SELECT COUNT(*) FROM test_core_requests WHERE state='cancelled'`) != 1 {
			t.Fatal("cleanup changed terminal outcome")
		}
	})
	t.Run("shared_admission_transaction_blocks_close_until_settlement_boundary", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, &coreFixture{})
		d := desired()
		state := observe(t, s, d)
		apply(t, s, cmd(state, "Activate"))
		state, _ = s.Read(context.Background(), d.CRUID)
		tx, err := f.db.BeginTx(context.Background(), &sql.TxOptions{Isolation: sql.LevelReadCommitted})
		if err != nil {
			t.Fatal(err)
		}
		defer tx.Rollback()
		var capacityID int
		if err = tx.QueryRowContext(context.Background(), "SELECT id FROM test_core_capacity WHERE id=1 FOR UPDATE NOWAIT").Scan(&capacityID); err != nil {
			t.Fatal(err)
		}
		binding, err := s.LockActive(context.Background(), tx, d.CRUID)
		if err != nil || binding != *state.Active {
			t.Fatal("core admission binding", err)
		}
		closed := make(chan error, 1)
		go func() { c := cmd(state, "CloseAdmission"); c.Target = nil; closed <- s.Apply(context.Background(), *c) }()
		if err = <-closed; err != release.ErrConflict {
			t.Fatal("closure bypassed core capacity lock", err)
		}
		if err = tx.Commit(); err != nil {
			t.Fatal(err)
		}
		c := cmd(state, "CloseAdmission")
		c.Target = nil
		apply(t, s, c)
		denied, err := f.db.BeginTx(context.Background(), &sql.TxOptions{Isolation: sql.LevelReadCommitted})
		if err != nil {
			t.Fatal(err)
		}
		defer denied.Rollback()
		if _, err = s.LockActive(context.Background(), denied, d.CRUID); err != release.ErrConflict {
			t.Fatal("new admission after close", err)
		}
	})
	t.Run("parallel_generations_do_not_lower_fence_or_epoch", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, &coreFixture{})
		d := desired()
		observe(t, s, d)
		var wg sync.WaitGroup
		for _, generation := range []int64{2, 3, 4, 5} {
			wg.Add(1)
			go func(g int64) {
				defer wg.Done()
				next := d
				next.Generation = g
				_, err := s.Observe(context.Background(), next)
				if err != nil && err != release.ErrConflict {
					t.Error(err)
				}
			}(generation)
		}
		wg.Wait()
		d.Generation = 6
		state := observe(t, s, d)
		if state.Generation != 6 || state.Candidate.Epoch < 2 || count(t, f.db, `SELECT MAX(activation_epoch) FROM publications`) != state.Candidate.Epoch {
			t.Fatal("non-monotonic state")
		}
	})
	t.Run("migration_checksum_conflict", func(t *testing.T) {
		f := databaseFixture(t)
		_, err := f.db.Exec(`UPDATE release_schema_migrations SET sha256=REPEAT('0',64)`)
		if err != nil {
			t.Fatal(err)
		}
		if Migrate(context.Background(), f.db) != release.ErrConflict {
			t.Fatal("changed migration accepted")
		}
	})
	t.Run("concurrent_activation_has_one_winner", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, &coreFixture{})
		state := observe(t, s, desired())
		commands := []*release.Command{cmd(state, "Activate"), cmd(state, "Activate")}
		start := make(chan struct{})
		results := make(chan error, 2)
		for _, c := range commands {
			go func(c *release.Command) { <-start; results <- s.Apply(context.Background(), *c) }(c)
		}
		close(start)
		winners := 0
		for range commands {
			err := <-results
			if err == nil {
				winners++
			} else if err != release.ErrConflict {
				t.Fatal(err)
			}
		}
		if winners != 1 || count(t, f.db, `SELECT COUNT(*) FROM release_operations`) != 1 || count(t, f.db, `SELECT COUNT(*) FROM publications WHERE activated=TRUE`) != 1 {
			t.Fatal("CAS had multiple winners")
		}
	})
	t.Run("migration_resume_and_unversioned_tables_are_not_adopted", func(t *testing.T) {
		f := databaseFixture(t)
		if _, err := f.db.Exec(`UPDATE release_schema_migrations SET state='Applying'`); err != nil {
			t.Fatal(err)
		}
		if _, err := f.db.Exec(`DROP TABLE release_operations`); err != nil {
			t.Fatal(err)
		}
		if err := Migrate(context.Background(), f.db); err != nil {
			t.Fatal("partial migration resume", err)
		}
		if _, err := f.db.Exec(`DELETE FROM release_schema_migrations`); err != nil {
			t.Fatal(err)
		}
		if err := Migrate(context.Background(), f.db); err != release.ErrConflict {
			t.Fatal("unowned tables adopted", err)
		}
	})
	t.Run("least_privilege_cannot_write_core_or_run_DDL", func(t *testing.T) {
		f := databaseFixture(t)
		user := "maas_pub_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
		password := uuid.NewString()
		// Both literals are generated here from UUID hex, never user input. MySQL
		// does not accept a prepared-statement marker in IDENTIFIED BY.
		if _, err := f.admin.Exec("CREATE USER '" + user + "'@'localhost' IDENTIFIED BY '" + password + "'"); err != nil {
			t.Fatal("test user creation", err)
		}
		t.Cleanup(func() { _, _ = f.admin.Exec("DROP USER '" + user + "'@'localhost'") })
		permissions := map[string]string{"release_links": "SELECT,INSERT,UPDATE", "release_revisions": "SELECT,INSERT", "publish_intents": "SELECT,INSERT", "publications": "SELECT,INSERT,UPDATE", "active_model_bindings": "SELECT,INSERT,UPDATE,DELETE", "resource_inventory": "SELECT,INSERT,UPDATE", "release_operations": "SELECT,INSERT"}
		for table, privileges := range permissions {
			if _, err := f.admin.Exec("GRANT " + privileges + " ON `" + f.name + "`." + table + " TO '" + user + "'@'localhost'"); err != nil {
				t.Fatal(err)
			}
		}
		cfg := *f.config
		cfg.User = user
		cfg.Passwd = password
		publisher, err := sql.Open("mysql", cfg.FormatDSN())
		if err != nil {
			t.Fatal(err)
		}
		defer publisher.Close()
		s := testStore(t, publisher, nil)
		d := desired()
		observe(t, s, d)
		for _, table := range []string{"test_core_capacity", "test_core_requests", "test_core_slots"} {
			if _, err = f.admin.Exec("GRANT SELECT ON `" + f.name + "`." + table + " TO '" + user + "'@'localhost'"); err != nil {
				t.Fatal(err)
			}
		}
		withCore := testStore(t, publisher, &coreFixture{})
		state := observe(t, withCore, d)
		apply(t, withCore, cmd(state, "Activate"))
		for _, write := range []string{`UPDATE test_core_unknown_hold SET amount=0`, `DELETE FROM test_core_slots`, `UPDATE test_core_capacity SET id=2`, `CREATE TABLE forbidden(id INT)`, `DELETE FROM release_links`, `DELETE FROM release_operations`, `UPDATE release_revisions SET revision=REPEAT('0',64)`} {
			if _, err := publisher.Exec(write); err == nil {
				t.Fatal("publisher got core/DDL write permission")
			}
		}
		if count(t, f.db, `SELECT amount FROM test_core_unknown_hold`) != 123456 {
			t.Fatal("core hold was changed")
		}
	})
	t.Run("counter_exhaustion_never_wraps", func(t *testing.T) {
		f := databaseFixture(t)
		s := testStore(t, f.db, nil)
		d := desired()
		observe(t, s, d)
		if _, err := f.db.Exec(`UPDATE release_links SET reconcile_epoch=?`, maxCounter); err != nil {
			t.Fatal(err)
		}
		d.Generation++
		if _, err := s.Observe(context.Background(), d); err != release.ErrConflict {
			t.Fatal("fence wrapped", err)
		}
		if count(t, f.db, `SELECT COUNT(*) FROM publications`) != 1 {
			t.Fatal("overflow created publication")
		}
	})
	t.Run("committed_ACK_loss_does_not_duplicate_publication_or_activation", testACKLoss)
}

// A connector wrapper loses ONLY the client-visible commit ACK, after the real
// server commits. It is entirely test code and does not change production Store.
type dropConnector struct {
	driver.Connector
	drop *atomic.Bool
}

func (c dropConnector) Connect(ctx context.Context) (driver.Conn, error) {
	conn, err := c.Connector.Connect(ctx)
	if err != nil {
		return nil, err
	}
	return &dropConn{Conn: conn, drop: c.drop}, nil
}

type dropConn struct {
	driver.Conn
	drop *atomic.Bool
}

func (c *dropConn) BeginTx(ctx context.Context, o driver.TxOptions) (driver.Tx, error) {
	tx, err := c.Conn.(driver.ConnBeginTx).BeginTx(ctx, o)
	if err != nil {
		return nil, err
	}
	return dropTx{Tx: tx, drop: c.drop}, nil
}

type dropTx struct {
	driver.Tx
	drop *atomic.Bool
}

func (t dropTx) Commit() error {
	if err := t.Tx.Commit(); err != nil {
		return err
	}
	if t.drop.Swap(false) {
		return errors.New("test: committed ACK lost")
	}
	return nil
}
func testACKLoss(t *testing.T) {
	f := databaseFixture(t)
	connector, err := mysql.NewConnector(f.config)
	if err != nil {
		t.Fatal(err)
	}
	drop := &atomic.Bool{}
	wrapped := sql.OpenDB(dropConnector{Connector: connector, drop: drop})
	defer wrapped.Close()
	s := testStore(t, wrapped, &coreFixture{})
	d := desired()
	drop.Store(true)
	if _, err = s.Observe(context.Background(), d); err != ErrCommitUnknown {
		t.Fatal("expected uncertain commit", err)
	}
	restarted := testStore(t, f.db, &coreFixture{})
	state := observe(t, restarted, d)
	if count(t, f.db, `SELECT COUNT(*) FROM publications`) != 1 || state.Candidate.Epoch != 1 {
		t.Fatal("uncertain Observe duplicated publication")
	}
	activation := cmd(state, "Activate")
	drop.Store(true)
	if err = s.Apply(context.Background(), *activation); err != ErrCommitUnknown {
		t.Fatal("expected activation ACK loss", err)
	}
	apply(t, restarted, activation)
	if count(t, f.db, `SELECT COUNT(*) FROM release_operations`) != 1 || count(t, f.db, `SELECT COUNT(*) FROM publications WHERE activated=TRUE`) != 1 {
		t.Fatal("uncertain activation replayed")
	}
	pub := state.Candidate.PublicationID
	e := release.Entry{Owner: d.CRUID, Publication: pub, Digest: d.Revision, Ref: api.ResourceRef{APIVersion: "v1", Kind: "ConfigMap", Namespace: d.Namespace, Name: "ack-bind", Ownership: "exclusive", PublicationID: &pub}}
	if err = restarted.Intent(context.Background(), e); err != nil {
		t.Fatal(err)
	}
	e.Ref.UID = uuid.NewString()
	drop.Store(true)
	if err = s.Bind(context.Background(), e); err != ErrCommitUnknown {
		t.Fatal("expected UID bind ACK loss", err)
	}
	if err = restarted.Bind(context.Background(), e); err != nil {
		t.Fatal("UID bind recovery", err)
	}
	entries, err := restarted.List(context.Background(), d.CRUID, pub)
	if err != nil || len(entries) != 1 || entries[0].Ref.UID != e.Ref.UID {
		t.Fatal("UID was not durable after ACK loss", err)
	}
}
