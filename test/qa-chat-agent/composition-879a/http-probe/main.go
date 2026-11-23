package main
import("context";"encoding/json";"io";"net/http";"os";"strings";"time")
func main(){
 var in struct{Method string `json:"method"`;Path string `json:"path"`;Headers map[string]string `json:"headers"`;Body string `json:"body"`}
 if json.NewDecoder(os.Stdin).Decode(&in)!=nil{os.Exit(2)}
 ctx,cancel:=context.WithTimeout(context.Background(),8*time.Second);defer cancel()
 req,e:=http.NewRequestWithContext(ctx,in.Method,"http://127.0.0.1:8080"+in.Path,strings.NewReader(in.Body));if e!=nil{os.Exit(2)}
 for k,v:=range in.Headers{if k=="Host"{req.Host=v}else{req.Header.Set(k,v)}}
 client:=&http.Client{Transport:&http.Transport{Proxy:nil,DisableKeepAlives:true},Timeout:9*time.Second}
 response,e:=client.Do(req);if e!=nil{json.NewEncoder(os.Stdout).Encode(map[string]any{"error":"owned HTTP transport unavailable"});return};defer response.Body.Close()
 body,e:=io.ReadAll(io.LimitReader(response.Body,2<<20));if e!=nil{os.Exit(2)}
 json.NewEncoder(os.Stdout).Encode(map[string]any{"status":response.StatusCode,"headers":response.Header,"body":string(body)})
}
