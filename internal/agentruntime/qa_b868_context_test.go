package agentruntime
import("context";"encoding/json";"testing";"time";"github.com/google/uuid")
func TestQAB868TrustedToolContext(t *testing.T){
 if _,ok:=ToolExecutionFrom(context.Background());ok{t.Fatal("unbound context trusted")}
 tool:=controlledTool(false);seen:=[]ToolExecution{};modelCalls:=0
 tool.f=func(ctx context.Context)(string,error){v,ok:=ToolExecutionFrom(ctx);if !ok{t.Error("trusted binding absent")};deadline,_:=ctx.Deadline();if !v.Deadline.Equal(deadline){t.Error("deadline not actual tool context")};seen=append(seen,v);return "safe",nil}
 h,m,_:=setupAR(t,func(_ context.Context,r Request,emit func(string)error)(Response,error){modelCalls++;if modelCalls==1{return Response{RequestID:r.RequestID,TerminalConfirmed:true,Finish:"tool_calls",Usage:arUsage(),Calls:[]Call{{ID:"call-a",Name:"controlled_tool",Arguments:json.RawMessage("{}")},{ID:"call-b",Name:"controlled_tool",Arguments:json.RawMessage("{}")}}},nil};if e:=emit("done");e!=nil{return Response{},e};return Response{RequestID:r.RequestID,TerminalConfirmed:true,Finish:"stop",Usage:arUsage()},nil},nil,tool)
 sid,etag:=arCreateSession(t,h);in:=arInput("agent");in.Tools=[]ARToolRef{{Name:"controlled_tool",Revision:"1"}};rid:=arSubmit(t,h,sid,etag,in)
 forged:=context.WithValue(context.Background(),toolExecutionKey{},ToolExecution{Principal:Principal{ID:"forged"},SessionID:"forged",IdempotencyKey:"forged"})
 if e:=h.Service.Drive(forged,arActor,sid,rid);e!=nil{t.Fatal(e)}
 doc,e:=h.Service.Get(context.Background(),arActor,sid);if e!=nil{t.Fatal(e)};r:=run(&doc,rid)
 if len(seen)!=2||len(r.Steps)!=2||len(r.Steps[0].Calls)!=2{t.Fatal("unexpected control flow",seen)}
 for i,v:=range seen{if v.Principal.ID!=arActor.ID||v.Principal.Revision!=arActor.Revision||!v.Principal.Permissions[tool.Spec().Permission]||v.SessionID!=sid||v.RunID!=rid||v.TraceID!=rid||v.StepID!=r.Steps[0].ID||v.RequestID!=r.Steps[0].RequestID||v.ToolCallID!=r.Steps[0].Calls[i].ID||v.Fence!=r.AR.Fence||v.IdempotencyKey=="forged"||v.Deadline.After(r.Deadline)||v.Deadline.Before(time.Now().Add(-time.Second)){t.Fatal("untrusted or stale metadata",v)};if _,e=uuid.Parse(v.IdempotencyKey);e!=nil{t.Fatal(e)}}
 if seen[0].IdempotencyKey==seen[1].IdempotencyKey{t.Fatal("two calls share key")}
 before:=doc.Revision;_ = h.Service.Drive(context.Background(),arActor,sid,rid);after,_:=h.Service.Get(context.Background(),arActor,sid)
 if after.Revision!=before||tool.calls.Load()!=2||m.calls.Load()!=2{t.Fatal("completed replay wrote or executed")}
 t.Logf("session=%s run=%s child=%s tools=2 trusted binding=true caller forgery overwritten=true",sid,rid,r.Steps[0].RequestID)
}
func TestQAB868ToolArgumentsCannotSupplyContext(t *testing.T){
 tool:=controlledTool(false)
 h,_,_:=setupAR(t,func(_ context.Context,r Request,_ func(string)error)(Response,error){return Response{RequestID:r.RequestID,TerminalConfirmed:true,Finish:"tool_calls",Usage:arUsage(),Calls:[]Call{{ID:"bad-args",Name:"controlled_tool",Arguments:json.RawMessage(`{"principal_id":"forged","idempotency_key":"forged"}`)}}},nil},nil,tool)
 sid,etag:=arCreateSession(t,h);in:=arInput("agent");in.Tools=[]ARToolRef{{Name:"controlled_tool",Revision:"1"}};rid:=arSubmit(t,h,sid,etag,in)
 if e:=h.Service.Drive(context.Background(),arActor,sid,rid);e!=nil{t.Fatal(e)}
 doc,e:=h.Service.Get(context.Background(),arActor,sid);if e!=nil{t.Fatal(e)}
 if tool.calls.Load()!=0||run(&doc,rid).Status!="failed"{t.Fatal("untrusted tool arguments executed")}
}
