package agentruntime

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
)

func TestMySQLAR1CommandsRestartAndTwoReplicaClaim(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("real disposable MySQL socket not provided")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("refusing non-disposable MySQL")
	}
	ctx := context.Background()
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	admin, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer admin.Close()
	name := "ar1_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.Exec("CREATE DATABASE " + name); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP DATABASE " + name)
	cfg.DBName = name
	db, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	if e = Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	store := MySQLStore{DB: db}
	h, model, _ := setupAR(t, arPlain, store)
	create := ARCreate{OperationID: uuid.NewString(), Title: "SQL", Alias: "controlled"}
	first := arDecode(t, arHTTP(t, h, "POST", "sessions", create, "", "Conversation", 201))
	sid := first["id"].(string)
	// Fresh service/DB connection reads the original mapping and events; no POST.
	otherDB, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer otherDB.Close()
	other, _, _ := setupAR(t, arPlain, MySQLStore{DB: otherDB})
	arHTTP(t, other, "GET", "session-creation-commands/"+create.OperationID, nil, "", "SessionCreationCommand", 200)
	in := arInput("chat")
	rid := arSubmit(t, h, sid, "\"1\"", in)
	started, release := make(chan struct{}), make(chan struct{})
	model.f = func(ctx context.Context, r Request, emit func(string) error) (Response, error) {
		close(started)
		<-release
		return arPlain(ctx, r, emit)
	}
	var wg sync.WaitGroup
	wg.Add(1)
	var driveErr error
	go func() { defer wg.Done(); driveErr = h.Service.Drive(ctx, arActor, sid, rid) }()
	<-started
	if e = other.Service.Drive(ctx, arActor, sid, rid); e != ErrConflict {
		t.Fatal("second replica claimed active run", e)
	}
	close(release)
	wg.Wait()
	if driveErr != nil {
		t.Fatal(driveErr)
	}
	arHTTP(t, other, "GET", "sessions/"+sid, nil, "", "Snapshot", 200)
	arHTTP(t, other, "GET", "sessions/"+sid+"/runs/"+rid+"/events?page_size=100", nil, "", "EventPage", 200)
	if model.calls.Load() != 1 {
		t.Fatal("duplicate model execution")
	}
	var count int
	if e = db.QueryRow("SELECT COUNT(*) FROM agent_sessions_v1").Scan(&count); e != nil || count != 1 {
		t.Fatal(count, e)
	}
	// An unavailable reader is 503, not an authoritative no-operation assertion.
	if e = otherDB.Close(); e != nil {
		t.Fatal(e)
	}
	arHTTP(t, other, "GET", "session-creation-commands/"+create.OperationID, nil, "", "Error", 503)
}
