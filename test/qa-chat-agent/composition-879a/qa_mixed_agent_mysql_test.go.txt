package kernel
import("context";"encoding/json";"testing";"time";"github.com/google/uuid";a "github.com/jianzi123/maas/internal/agentruntime")
type qaMixedLedgerModel struct{base agentLedgerModel}
func(m *qaMixedLedgerModel)Supports(context.Context,a.Model)error{return nil}
func(m *qaMixedLedgerModel)Generate(ctx context.Context,r a.Request,emit func(string)error)(a.Response,error){
 if m.base.calls==0{return m.base.Generate(ctx,r,emit)}
 m.base.calls++;in:=m.base.f.input(m.base.t);in.RequestID=r.RequestID;snap,e:=m.base.f.core.Admit(ctx,m.base.f.gate,in);if e!=nil{return a.Response{},e}
 fin:=finalFor(snap);fin.Result="succeeded";fin.Submitted=true;fin.EvidenceRef=uuid.NewString()
 if e=m.base.f.core.Finalize(ctx,fin);e!=nil{return a.Response{},e};if e=m.base.f.core.Finalize(ctx,fin);e!=nil{return a.Response{},e}
 if e=emit("42");e!=nil{return a.Response{},e}
 money:=readCounter(m.base.t,m.base.f,"money")
 return a.Response{RequestID:r.RequestID,TerminalConfirmed:true,Finish:"stop",Usage:a.Usage{Currency:"TST",Complete:false,Groups:[]a.ARUsageGroup{{Currency:"TST",Price:m.base.f.profile.Price.Version,KnownTokens:"0",KnownMoney:"0",HeldTokens:"140",HeldMoney:money.Held,InflightTokens:"0",InflightMoney:"0"}}}},nil
}
func TestQAAgentMixedKnownUnknownLedger(t *testing.T){
 f:=setup(t,2);ctx:=context.Background();if e:=a.Migrate(ctx,f.db);e!=nil{t.Fatal(e)}
 model:=&qaMixedLedgerModel{base:agentLedgerModel{t:t,f:f}};registry,_:=a.NewRegistry(a.Calculator{})
 limits:=a.Limits{Currency:"TST",Steps:4,Calls:4,Tokens:1000,Money:10000000,Duration:10*time.Second,ToolTimeout:time.Second,ApprovalTTL:time.Minute,InputBytes:32768,OutputBytes:8192,Events:500}
 s,e:=a.NewService(a.MySQLStore{DB:f.db},model,registry,limits);if e!=nil{t.Fatal(e)}
 p:=a.Principal{ID:"75b49016-0aa4-42fc-ac6d-9f67318c1dce",Revision:"1",Permissions:map[string]bool{"tools.calculate":true}};s.Reauthorize=func(_ context.Context,p a.Principal)(a.Principal,error){return p,nil};s.CountContext=func(_ context.Context,r a.Request)(int64,error){b,_:=json.Marshal(r);return int64(len(b)),nil}
 v,e:=s.Create(ctx,p,"mixed known and unknown");if e!=nil{t.Fatal(e)}
 in:=a.Submit{ClientID:uuid.NewString(),Text:"multiply",Mode:"agent",Model:a.Model{Alias:"controlled",Source:"controlled-test",Revision:"1",Protocol:"tools-v1"}}
 in.AR=&a.ARExecution{Limits:a.ARLimits{Steps:4,Calls:4,Tools:4,Duration:10000,ToolTimeout:1000,OutputBytes:8192,ContextTokens:32768,NoProgress:3,Tokens:"1000",Money:"10000000",Currency:"TST"},Tools:[]a.ARToolRef{{Name:"bounded_arithmetic",Revision:"1"}},Created:time.Now().UTC(),Fence:1,PolicyRevision:"controlled-policy"}
 r,e:=s.Submit(ctx,p,v.ID,in);if e!=nil{t.Fatal(e)};if e=s.Drive(ctx,p,v.ID,r.ID);e!=nil{t.Fatal(e)}
 got,e:=s.Get(ctx,p,v.ID);if e!=nil||len(got.Runs)!=1||len(got.Runs[0].Steps)!=2{t.Fatal(e,got)}
 budget:=readCounter(t,f,"tokens");money:=readCounter(t,f,"money");if budget.Known!="19"||budget.Held!="140"||budget.Reserved!="0"||money.Held!="520000"{t.Fatal("actual ledger",budget,money)}
 assertSQL(t,f.db,"SELECT COUNT(*) FROM generation_requests",2);assertSQL(t,f.db,"SELECT COUNT(*) FROM usage_events",2);assertSQL(t,f.db,"SELECT SUM(finalized_total) FROM usage_daily",2)
 found:=false
 for _,ev:=range got.Events{if ev.Type!="run.completed"{continue};var wire map[string]any;if e=json.Unmarshal(ev.Wire,&wire);e!=nil{t.Fatal(e)};payload:=wire["data"].(map[string]any);groups:=payload["usage_groups"].([]any);if len(groups)!=1||payload["aggregation_complete"]!=false{t.Fatal(payload)};g:=groups[0].(map[string]any);if g["known_tokens"]!="19"||g["held_tokens"]!="140"||g["held_money_atomic"]!="520000"{t.Fatal("parent aggregate",g)};found=true}
 if !found{t.Fatal("no durable parent completion event")}
 for i:=0;i<2;i++{same,e:=s.Submit(ctx,p,v.ID,in);if e!=nil||same.ID!=r.ID{t.Fatal(e)};if _,e=s.Events(ctx,p,v.ID,r.ID,0);e!=nil{t.Fatal(e)}}
 if model.base.calls!=2||readCounter(t,f,"tokens")!=budget||readCounter(t,f,"money")!=money{t.Fatal("replay changed ledger")}
 for _,step:=range got.Runs[0].Steps{assertSQL(t,f.db,"SELECT COUNT(*) FROM usage_events WHERE request_id=?",1,step.RequestID);t.Logf("parent=%s child_request=%s SQL usage once",r.ID,step.RequestID)}
 t.Log("known_tokens=19 held_tokens=140 held_money=520000 two_children=2 two_usage=2 parent_complete=false replay_no_write=true")
}
