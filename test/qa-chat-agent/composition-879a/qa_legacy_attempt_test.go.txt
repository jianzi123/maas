package agentruntime
import("context";"encoding/json";"testing")
func TestQAARLegacyAttemptConservative(t *testing.T){
 tool:=controlledTool(true)
 h,m,_:=setupAR(t,func(_ context.Context,r Request,_ func(string)error)(Response,error){return Response{RequestID:r.RequestID,TerminalConfirmed:true,Finish:"tool_calls",Calls:[]Call{{ID:"legacy-call",Name:"controlled_tool",Arguments:json.RawMessage("{}")}},Usage:arUsage()},nil},nil,tool)
 sid,tag:=arCreateSession(t,h);in:=arInput("agent");in.Tools=[]ARToolRef{{Name:"controlled_tool",Revision:"1"}};rid:=arSubmit(t,h,sid,tag,in)
 if e:=h.Service.Drive(context.Background(),arActor,sid,rid);e!=nil{t.Fatal(e)}
 for _,state:=range []string{"executing","completed","failed","unknown","cancelled"}{t.Run(state,func(t *testing.T){
  _,e:=h.Service.mutate(context.Background(),arActor,sid,func(v *Session)error{r:=run(v,rid);c:=&r.Steps[0].Calls[0];c.State=state;c.Attempt=0;return nil});if e!=nil{t.Fatal(e)}
  body:=arDecode(t,arHTTP(t,h,"GET","sessions/"+sid+"/runs/"+rid+"/tool-calls",nil,"","ToolCallPage",200))
  got:=body["data"].([]any)[0].(map[string]any)["attempt"].(float64);want:=float64(1);if state=="cancelled"{want=0};if got!=want{t.Fatal("legacy attempt",state,got,want)}
 })}
 if m.calls.Load()!=1||tool.calls.Load()!=0{t.Fatal("projection dispatched work")}
}
