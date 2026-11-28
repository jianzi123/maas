"""Supported Compose install/upgrade: stop scheduler, run a FRESH audit, then start.

No audit receipt/skip flag. Automatic runtime restarts and direct binary/primitive
YAML invocation are not continuous authorization-drift enforcement.
"""
import argparse,json,subprocess
from pathlib import Path


def install(command, execute):
    config=execute(command+["config","--format","json"],capture=True)
    services=json.loads(config)["services"]
    if not {"migrate","maas","web"}.issubset(services):raise ValueError("same-version installer services required")
    if "mysql" in services:execute(command+["up","-d","--wait","--wait-timeout","300","mysql"])
    execute(command+["stop","maas","web"])
    # A completed canonical migrate container is NOT a fresh installation audit.
    execute(command+["run","--rm","--no-deps","migrate"])
    execute(command+["up","--no-deps","-d","--wait","--wait-timeout","180","maas","web"])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file",type=Path,default=Path("compose.yaml"));p.add_argument("--project");p.add_argument("--docker",default="docker")
    a=p.parse_args();file=a.file.resolve()
    command=[a.docker,"compose","--parallel","1","--project-directory",str(file.parent),"-f",str(file)]
    if a.project:command += ["-p",a.project]
    def execute(args,capture=False):
        result=subprocess.run(args,capture_output=capture,text=True,timeout=600)
        if result.returncode:raise RuntimeError("installer step failed with exit "+str(result.returncode))
        return result.stdout if capture else None
    try:install(command,execute)
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.TimeoutExpired):
        print("Installation/audit failed; application was not started by this invocation. Preserve database/Secrets and inspect the original step.")
        return 1
    return 0


if __name__=="__main__":raise SystemExit(main())
