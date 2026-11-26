"""One disabled-plan Windows -> WSL control pipe, no performance measurements."""
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path.cwd();meta=json.loads((root/'inputs/aa-cpu01/provenance.json').read_bytes());src=Path(meta['source']);base=Path(meta['short_root'])/'cross';base.mkdir(exist_ok=False)
def linux(path):
 p=Path(path).resolve();return '/mnt/'+p.drive[0].lower()+'/'+p.relative_to(p.anchor).as_posix()
guard=Path(meta['short_root'])/'win1/guard';plan=Path(meta['short_root'])/'win1/disabled-plan.json'
ready=base/'ready.json';cmd=['wsl','-d','Ubuntu-22.04','--exec','env','PYTHONPATH='+linux(guard)+':'+linux(src),'PYTHONDONTWRITEBYTECODE=1','python3','-u',linux(src/'run_aa_window.py'),'--plan',linux(plan),'--validate-lease-only','--control-timeout-ms','1800','--control-ready-file',linux(ready),'--output',linux(base)]
origin=time.monotonic_ns();child=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
receipt={'argv':cmd,'owned_windows_pid':child.pid,'protected_daemon_pid':meta['protected_daemon_pid']}
try:
 until=time.monotonic()+5
 while not ready.exists() and child.poll() is None and time.monotonic()<until:time.sleep(.005)
 assert ready.exists(),'WSL CPU readiness not reached'
 time.sleep(.18)
 driver=time.monotonic_ns()-origin
 lease={'window_id':'MAAS7_CROSS_CPU_ONLY','total_seconds':600,'stop_new_seconds':540,'driver_elapsed_at_send_ns':driver,'soft_remaining_ns':540_000_000_000-driver-1_000_000_000,'hard_remaining_ns':600_000_000_000-driver-1_000_000_000,'protected_daemon_pid':meta['protected_daemon_pid']}
 packet=json.dumps(lease,sort_keys=True).encode()+b'\n';(base/'stdin.bin').write_bytes(packet)
 stdout,stderr=child.communicate(packet,timeout=4);(base/'stdout.log').write_bytes(stdout);(base/'stderr.log').write_bytes(stderr)
 assert child.returncode==0,stderr[-400:]
 r=json.loads(stdout);assert r['lease_validated'] and not r['GPU_imports'];assert r['driver_elapsed_at_send_ns']==driver
 assert r['control_receive_elapsed_ns']>=180_000_000
 assert r['soft_remaining_at_receive_ns']==lease['soft_remaining_ns']-r['control_receive_elapsed_ns']
 assert r['hard_remaining_at_receive_ns']==lease['hard_remaining_ns']-r['control_receive_elapsed_ns']
 receipt.update(status='PASS',lease=lease,received=r,elapsed_ns=time.monotonic_ns()-origin,exit=child.returncode,stdin_sha256=hashlib.sha256(packet).hexdigest())
finally:
 if child.poll() is None:
  assert child.pid not in (os.getpid(),meta['protected_daemon_pid']);child.kill();child.wait(timeout=3)
 receipt['owned_child_collected']=child.poll() is not None
 (base/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt,indent=2))
