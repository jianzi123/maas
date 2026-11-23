package agentruntime
import("context";"encoding/json";"fmt";"testing")
func TestQAARStepAndToolPageRevisionRecovery(t *testing.T){
 count:=0
 h,m,_:=setupAR(t,func(_ context.Context,r Request,emit func(string)error)(Response,error){
  count++
  res:=Response{RequestID:r.RequestID,TerminalConfirmed:true,Usage:arUsage()}
  if count<=2{res.Finish="tool_calls";res.Calls=[]Call{{ID:fmt.Sprint("calc-",count),Name:"bounded_arithmetic",Arguments:json.RawMessage(fmt.Sprintf(`{"a":%d,"b":7,"op":"multiply"}`,count))}}}else{res.Finish="stop";if e:=emit("done");e!=nil{return res,e}}
  return res,nil
 },nil)
 sid,tag:=arCreateSession(t,h);rid:=arSubmit(t,h,sid,tag,arInput("agent"))
 if e:=h.Service.Drive(context.Background(),arActor,sid,rid);e!=nil{t.Fatal(e)}
 current,e:=h.Service.Get(context.Background(),arActor,sid);if e!=nil{t.Fatal(e)}
 if run(&current,rid).Status!="completed"||m.calls.Load()!=3{t.Fatal("controlled run did not complete",current)}
 tokens:=map[string]string{}
 for _,spec:=range []struct{kind,schema string;n int}{{"steps","StepPage",3},{"tool-calls","ToolCallPage",2}}{
  path:="sessions/"+sid+"/runs/"+rid+"/"+spec.kind
  first:=arDecode(t,arHTTP(t,h,"GET",path+"?page_size=1",nil,"",spec.schema,200))
  token,ok:=first["next_cursor"].(string);if !ok||token==""{t.Fatal("no second page",first)};tokens[spec.kind]=token
  arHTTP(t,h,"GET",path+"?page_size=1&cursor="+token+"x",nil,"","Error",400)
  seen:=map[string]bool{}
  for page:=first;;{
   for _,raw:=range page["data"].([]any){id:=raw.(map[string]any)["id"].(string);if seen[id]{t.Fatal("duplicate page ID",id)};seen[id]=true}
   next,_:=page["next_cursor"].(string);if next==""{break};page=arDecode(t,arHTTP(t,h,"GET",path+"?page_size=1&cursor="+next,nil,"",spec.schema,200))
  }
  if len(seen)!=spec.n{t.Fatal("page loss",spec.kind,len(seen))}
 }
 afterReads,_:=h.Service.Get(context.Background(),arActor,sid);if current.Revision!=afterReads.Revision||m.calls.Load()!=3{t.Fatal("GET mutated or replayed")}
 snap:=arHTTP(t,h,"GET","sessions/"+sid,nil,"","Snapshot",200)
 body:=arDecode(t,snap);in:=arInput("chat");in.Operation="edit";ref:=body["messages"].([]any)[0].(map[string]any)["id"].(string);in.Reference=&ref
 arSubmit(t,h,sid,snap.Header().Get("ETag"),in)
 for _,spec:=range []struct{kind,schema string;n int}{{"steps","StepPage",3},{"tool-calls","ToolCallPage",2}}{
  path:="sessions/"+sid+"/runs/"+rid+"/"+spec.kind
  err:=arDecode(t,arHTTP(t,h,"GET",path+"?page_size=1&cursor="+tokens[spec.kind],nil,"","Error",410))["error"].(map[string]any)
  if err["snapshot_required"]!=true||err["retryable"]!=false{t.Fatal(err)}
  fresh:=arDecode(t,arHTTP(t,h,"GET",path+"?page_size=1",nil,"",spec.schema,200));seen:=map[string]bool{}
  for page:=fresh;;{for _,raw:=range page["data"].([]any){id:=raw.(map[string]any)["id"].(string);if seen[id]{t.Fatal("recovery duplicate",id)};seen[id]=true};next,_:=page["next_cursor"].(string);if next==""{break};page=arDecode(t,arHTTP(t,h,"GET",path+"?page_size=1&cursor="+next,nil,"",spec.schema,200))}
  if len(seen)!=spec.n{t.Fatal("recovery loss",spec.kind,len(seen))}
 }
 if m.calls.Load()!=3{t.Fatal("recovery executed model")}
 t.Logf("session=%s original_run=%s steps=3 tools=2 model_calls=3 edit_invalidates_both=true GET_readonly=true",sid,rid)
}
