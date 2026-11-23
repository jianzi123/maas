package agentruntime
import("context";"database/sql";"encoding/json";"os";"path/filepath";"strings";"testing";"github.com/go-sql-driver/mysql";"github.com/google/uuid")
func TestQASeedProductInFlight(t *testing.T){
 socket:=os.Getenv("MAAS_MYSQL_TEST_SOCKET")
 if os.Getenv("MAAS_DISPOSABLE_MYSQL")!="1"||!strings.HasPrefix(socket,"/tmp/maas11-mysql.")||os.Getenv("MAAS_QA_SEED_DB")!="qa_product_879a"{t.Fatal("owned disposable seed only")}
 cfg:=mysql.NewConfig();cfg.User="root";cfg.Net="unix";cfg.Addr=socket;cfg.DBName="qa_product_879a";cfg.ParseTime=true
 db,e:=sql.Open("mysql",cfg.FormatDSN());if e!=nil{t.Fatal(e)};defer db.Close()
 h,m,_:=setupAR(t,arPlain,MySQLStore{DB:db});sid,etag:=arCreateSession(t,h);rid:=arSubmit(t,h,sid,etag,arInput("chat"));child:=uuid.NewString()
 _,e=h.Service.mutate(context.Background(),arActor,sid,func(v *Session)error{r:=run(v,rid);r.Status="running";r.Executor="qa-prior-crashed-owner";r.Checkpoint=Checkpoint{Phase:"model_inflight",RequestID:child};r.Steps=[]Step{{ID:uuid.NewString(),Number:1,RequestID:child,State:"running",InputHash:strings.Repeat("a",64)}};return nil});if e!=nil{t.Fatal(e)}
 if m.calls.Load()!=0{t.Fatal("seed executed model")}
 b,_:=json.Marshal(map[string]string{"session_id":sid,"run_id":rid,"child_request_id":child,"principal_id":arActor.ID,"fixture":"SQL persisted crash checkpoint; no upstream dispatched"})
 if e=os.WriteFile(filepath.Join(os.Getenv("MAAS_QA_ARTIFACT_DIR"),"app-seed.json"),b,0600);e!=nil{t.Fatal(e)}
 t.Logf("owned SQL checkpoint session=%s run=%s child=%s model_calls=0",sid,rid,child)
}
