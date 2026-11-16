"""Associate two diagnostic source files; never promotes clock/identity trust."""
import argparse,hashlib,json
from pathlib import Path
from client_capture import associate,CaptureRejected

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--client-source",type=Path,required=True)
 p.add_argument("--go-sample",type=Path,required=True)
 p.add_argument("--expected-go-sha256",required=True)
 p.add_argument("--output",type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise CaptureRejected("fresh output required")
 raw=a.go_sample.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=a.expected_go_sha256:raise CaptureRejected("Go source digest")
 result=associate(json.loads(a.client_source.read_text(encoding="utf-8")),json.loads(raw))
 result["go_raw_sha256"]=a.expected_go_sha256
 result["client_raw_sha256"]=hashlib.sha256(a.client_source.read_bytes()).hexdigest()
 encoded=json.dumps(result,indent=2,allow_nan=False)+"\n"
 with a.output.open("x",encoding="utf-8") as f:f.write(encoded)
 print(json.dumps({"associated_request_only":True,"trusted_source":False,"cross_clock_merged":False,"d1_overall_complete":False}))

if __name__=="__main__":
 try:main()
 except (OSError,ValueError,KeyError,TypeError):
  print("Client/Go association rejected identity/digest/output",file=__import__("sys").stderr)
  raise SystemExit(2)
