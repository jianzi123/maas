"""CPU-only local control deadlines; distinct from inference measurement clocks."""
import hashlib,io,json,os,platform,select,sys,time
from pathlib import Path
from aa_protocol import CONFIG,need,check_budget,read_lease
from cadence_protocol import digest

def clock_domain():
    identity=[sys.platform,platform.node(),time.get_clock_info("monotonic").implementation]
    boot=Path("/proc/sys/kernel/random/boot_id")
    if sys.platform.startswith("linux") and boot.exists():identity.append(boot.read_text().strip())
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

def control_scope(window_id,parent_pid,origin_ns):
    return {"kind":"local-monotonic-v1","domain":clock_domain(),"origin_ns":origin_ns,
            "window_id":window_id,"owner_pid":parent_pid}

def control_binding(lease,control):
    return digest({"lease":lease,"control":control})

def validate_control_shape(job):
    c=job["budget_control"]
    need(c["kind"]=="local-monotonic-v1" and isinstance(c["domain"],str) and len(c["domain"])==64,"control clock kind/domain")
    need(type(c["origin_ns"]) is int and c["origin_ns"]>0,"control clock origin")
    need(c["window_id"]==job["window_id"] and c["owner_pid"]==job["parent_pid"],"control owner/window")
    need(job["control_binding_sha256"]==control_binding(job["budget"],c),"control binding hash")

def validate_job_time(job,now_ns=None,expected_binding=None):
    need(job.get("schema")=="P25-AA-job2","execution requires timed job2")
    validate_control_shape(job)
    expected=expected_binding if expected_binding is not None else os.environ.get("AA_PARENT_CONTROL_BINDING")
    need(expected is not None and job["control_binding_sha256"]==expected,"original parent control binding")
    need(job["budget_control"]["domain"]==clock_domain(),"foreign control clock")
    now=time.monotonic_ns() if now_ns is None else now_ns
    elapsed=now-job["budget_control"]["origin_ns"]
    need(0<=job["launch_parent_elapsed_ns"]<=elapsed,"future control origin/launch")
    need(elapsed<job["soft_parent_deadline_ns"]<=job["budget"]["soft_remaining_ns"],"late job / original soft budget")
    need(elapsed<job["hard_parent_deadline_ns"]<=job["budget"]["hard_remaining_ns"],"late job / original hard budget")
    return elapsed

def make_job(plan,phase,lease,control,lock_fd,bank_sha=None,bank_path=None,now_ns=None,expected_binding=None):
    check_budget(lease)
    elapsed=(time.monotonic_ns() if now_ns is None else now_ns)-control["origin_ns"]
    job={"schema":"P25-AA-job2","plan_sha256":digest(plan),"window_id":lease["window_id"],"process":phase,
         "parent_pid":control["owner_pid"],"research_lock_fd":lock_fd,"budget":lease,"budget_lease_sha256":digest(lease),
         "launch_parent_elapsed_ns":elapsed,"soft_parent_deadline_ns":lease["soft_remaining_ns"],
         "hard_parent_deadline_ns":lease["hard_remaining_ns"],"bank_sha256":bank_sha,"bank_path":bank_path,
         "budget_control":dict(control),"control_binding_sha256":control_binding(lease,control)}
    validate_job_time(job,now_ns,expected_binding if expected_binding is not None else control_binding(lease,control))
    return job

def _available_read(fd,remaining_ns):
    """Return None if waiting, b'' on EOF. Never blocks waiting for a pipe byte."""
    if os.name!="nt":
        ready,_,_=select.select([fd],[],[],min(.01,remaining_ns/1e9))
        return os.read(fd,4096) if ready else None
    import ctypes,msvcrt
    from ctypes import wintypes
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.GetFileType.argtypes=[wintypes.HANDLE];kernel.GetFileType.restype=wintypes.DWORD
    handle=msvcrt.get_osfhandle(fd);kind=kernel.GetFileType(handle)
    if kind==1:return os.read(fd,4096) # Regular file; no streaming peer to wait for.
    need(kind==3,"control input must be pipe or regular file")
    peek=kernel.PeekNamedPipe
    peek.argtypes=[wintypes.HANDLE,wintypes.LPVOID,wintypes.DWORD,wintypes.LPDWORD,wintypes.LPDWORD,wintypes.LPDWORD]
    peek.restype=wintypes.BOOL
    available=wintypes.DWORD()
    if not peek(handle,None,0,None,ctypes.byref(available),None):
        err=ctypes.get_last_error()
        if err in (109,232):return b""
        raise OSError(err,"PeekNamedPipe control read")
    if available.value:return os.read(fd,min(4096,available.value))
    time.sleep(min(.005,remaining_ns/1e9));return None

def receive_lease(stream,origin_ns,max_wait_ns=None):
    """Charge time BEFORE ready/read to the sent lease; intentionally conservative."""
    ceiling=CONFIG["resources"]["parent_stop_new_seconds"]*1_000_000_000
    wait=ceiling if max_wait_ns is None else max_wait_ns
    need(type(wait) is int and 0<wait<=ceiling,"control receive limit")
    deadline=origin_ns+wait;data=bytearray();fd=stream.fileno()
    while True:
        remaining=deadline-time.monotonic_ns()
        if remaining<=0:raise TimeoutError("control channel deadline before complete acceptance")
        chunk=_available_read(fd,remaining)
        if chunk is None:continue
        if chunk==b"":break
        data.extend(chunk);need(len(data)<=65536,"control frame too large")
        if bytes((10,)) in data:
            first,tail=bytes(data).split(bytes((10,)),1)
            need(not tail,"exactly one lease frame required")
            provisional=json.loads(first.decode("utf-8"));check_budget(provisional)
            deadline=min(deadline,origin_ns+provisional["soft_remaining_ns"])
    lease=read_lease(io.StringIO(bytes(data).decode("utf-8")))
    elapsed=time.monotonic_ns()-origin_ns
    need(0<=elapsed<lease["soft_remaining_ns"],"late control / original soft budget consumed")
    need(elapsed<lease["hard_remaining_ns"],"late control / original hard budget consumed")
    return lease,{"control_receive_elapsed_ns":elapsed,
                  "soft_remaining_at_receive_ns":lease["soft_remaining_ns"]-elapsed,
                  "hard_remaining_at_receive_ns":lease["hard_remaining_ns"]-elapsed,
                  "driver_elapsed_at_send_ns":lease["driver_elapsed_at_send_ns"],
                  "accounting":"origin before ready; overlap with sender may be charged twice, never credited"}

def supervise_owned(child,elapsed_ns,soft_ns,hard_ns,protected_pid,soft_action,
                    cleanup_grace_ns=10_000_000_000,record_reserve_ns=20_000_000_000):
    """The caller supplies ONE parent elapsed clock; never creates a child deadline."""
    need(child.pid!=protected_pid and child.pid!=os.getpid(),"protected PID")
    need(0<=soft_ns<hard_ns,"supervisor deadlines")
    sent=None;forced=False
    try:
        while child.poll() is None:
            now=elapsed_ns()
            if now>=soft_ns and sent is None:
                soft_action(child);sent=now
            if now>=min(soft_ns+cleanup_grace_ns,hard_ns-record_reserve_ns):
                child.kill();forced=True;break
            time.sleep(.005)
        rc=child.wait()
        return {"exit_code":rc,"soft_signal_ns":sent,"forced_kill":forced}
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
