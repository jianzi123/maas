import json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[3].parent
source=Path(__file__).resolve().parents[3]
out=Path(os.environ['MAAS_QA_OUT']).resolve();out.mkdir(parents=True,exist_ok=True)
tool=Path(os.environ['MAAS_QA_GO_ROOT'])
cache=source/'.cache/qa-go-build'
cache.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,GOROOT=str(tool),GOPATH=str(source/'.cache/gopath'),GOCACHE=str(cache),GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOMAXPROCS='2',CGO_ENABLED='0')
env['GOMODCACHE']=os.environ['MAAS_QA_GOMODCACHE']
go=str(tool/'bin/go.exe')
stage=sys.argv[1]
if stage in ('portable','portable-sdk','portable-trace','portable-files','portable-corrected'):
    cmd=[go,'test','-p=2','-overlay='+str(out/'overlay.json'),'-json','-count=1','-timeout=120s','-run=^(TestAR1|TestARReview|TestQAAR(Snapshot|Tool|Cursor|Step))','./internal/agentruntime']
elif stage in ('agent','kernel','installation'):
    env['GOOS']='linux';env['GOARCH']='amd64'
    package={'agent':'./internal/agentruntime','kernel':'./internal/kernel','installation':'./cmd/workbench'}[stage]
    cmd=[go,'test','-c','-vet=off','-p=2','-buildvcs=false','-o',str(out/(stage+'.test'))]
    if stage=='installation': cmd+=['-tags=localworkbench']

    cmd+=[package]
elif stage=='probe':
    env['GOOS']='linux';env['GOARCH']='amd64'
    cmd=[go,'build','-p=2','-buildvcs=false','-o',str(out/'qa-http-probe'),'./test/qa-chat-agent/composition-879a/http-probe']
elif stage=='service':
    env['GOOS']='linux';env['GOARCH']='amd64'
    cmd=[go,'build','-p=2','-buildvcs=false','-o',str(out/'maas-service'),'./cmd/maas-service']
else: raise ValueError(stage)
if stage=='portable-trace': cmd[2:2]=['-x','-vet=off','-buildvcs=false']
if stage in ('portable-files','portable-corrected'): cmd=[v for v in cmd if not v.startswith('-overlay=')]; cmd[2:2]=['-vet=off','-buildvcs=false']
assert not (out/(stage+'-command.json')).exists()
start=time.time()
with (out/(stage+'.stdout')).open('wb') as stdout,(out/(stage+'.stderr')).open('wb') as stderr:
    try:
        r=subprocess.run(cmd,cwd=source,env=env,stdout=stdout,stderr=stderr,timeout=420)
        code=r.returncode
    except subprocess.TimeoutExpired:
        code=124
record={'stage':stage,'command':cmd,'cwd':str(source),'exit':code,'elapsed_seconds':round(time.time()-start,3),'env':{k:env[k] for k in ['GOROOT','GOPATH','GOCACHE','GOMODCACHE','GOTOOLCHAIN','GOENV','GOPROXY','GOSUMDB','GOMAXPROCS','CGO_ENABLED']}}
(out/(stage+'-command.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record))
if code: print((out/(stage+'.stderr')).read_text(encoding='utf-8',errors='replace')[-3000:])
raise SystemExit(code)
