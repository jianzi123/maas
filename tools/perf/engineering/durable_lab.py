"""Crash/recovery experiment using TWO local SQLite files, never project MySQL/K8s."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing

PAYLOAD = {"cr_uid": "M1", "revision": "r7", "publication": "p7"}
COMMAND = "publish:M1:p7"
CRASH = {"prepared": 91, "effect": 92, "committed": 93}


def digest(payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return body, hashlib.sha256(body.encode()).hexdigest()


def connect(path):
    c = sqlite3.connect(path, timeout=2, isolation_level=None)
    c.execute("PRAGMA synchronous=FULL")
    return c


def initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with closing(connect(root / "journal.sqlite")) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY, fence INTEGER NOT NULL, deleted INTEGER NOT NULL)"
        )
        c.execute("INSERT OR IGNORE INTO owner VALUES(1,1,0)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS commands(
          id TEXT PRIMARY KEY, hash TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
          resource_uid TEXT, prepare_pid INTEGER NOT NULL, apply_writes INTEGER NOT NULL DEFAULT 0)"""
        )
    with closing(connect(root / "remote.sqlite")) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS resources(command TEXT PRIMARY KEY, hash TEXT NOT NULL, uid TEXT NOT NULL UNIQUE)"
        )


def _gate(c, fence):
    actual, deleted = c.execute("SELECT fence,deleted FROM owner WHERE id=1").fetchone()
    if deleted or actual != fence:
        raise ValueError("stale/deleted owner")


def prepare(root, command, payload, fence):
    body, h = digest(payload)
    c = connect(Path(root) / "journal.sqlite")
    try:
        c.execute("BEGIN IMMEDIATE")
        _gate(c, fence)
        row = c.execute(
            "SELECT hash,state,resource_uid FROM commands WHERE id=?", (command,)
        ).fetchone()
        if row:
            if row[0] != h:
                raise ValueError("same command different payload")
            result = (row[1], row[2])
        else:
            c.execute(
                "INSERT INTO commands(id,hash,payload,state,prepare_pid) VALUES(?,?,?,?,?)",
                (command, h, body, "prepared", os.getpid()),
            )
            result = ("prepared", None)
        c.commit()
        return result
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def remote_ensure(root, command, payload):
    # Fake external resource authority is durable, separate, and keyed by original command.
    _, h = digest(payload)
    c = connect(Path(root) / "remote.sqlite")
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT hash,uid FROM resources WHERE command=?", (command,)
        ).fetchone()
        if row:
            if row[0] != h:
                raise ValueError("foreign/conflicting resource")
            uid = row[1]
        else:
            uid = str(uuid.uuid4())
            c.execute("INSERT INTO resources VALUES(?,?,?)", (command, h, uid))
        c.commit()
        return uid
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def record_applied(root, command, payload, fence, uid):
    _, h = digest(payload)
    c = connect(Path(root) / "journal.sqlite")
    try:
        c.execute("BEGIN IMMEDIATE")
        _gate(c, fence)
        row = c.execute(
            "SELECT hash,state,resource_uid FROM commands WHERE id=?", (command,)
        ).fetchone()
        if row is None or row[0] != h:
            raise ValueError("journal conflict")
        if row[1] == "applied":
            if row[2] != uid:
                raise ValueError("UID mismatch")
        else:
            c.execute(
                "UPDATE commands SET state='applied',resource_uid=?,apply_writes=apply_writes+1 WHERE id=?",
                (uid, command),
            )
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def recover(root, command, payload, fence=1, fault=None, lose_fence=False):
    state, uid = prepare(root, command, payload, fence)
    if state == "applied":
        return {
            "state": state,
            "uid": uid,
            "pid": os.getpid(),
            "external_ensure_called": False,
        }
    if fault == "prepared":
        os._exit(CRASH[fault])
    uid = remote_ensure(root, command, payload)
    if fault == "effect":
        os._exit(CRASH[fault])
    if lose_fence:
        with closing(connect(Path(root) / "journal.sqlite")) as c:
            c.execute("UPDATE owner SET fence=fence+1 WHERE id=1")
    record_applied(root, command, payload, fence, uid)
    if fault == "committed":
        os._exit(CRASH[fault])
    return {
        "state": "applied",
        "uid": uid,
        "pid": os.getpid(),
        "external_ensure_called": True,
    }


def inspect(root):
    with closing(connect(Path(root) / "journal.sqlite")) as c:
        rows = c.execute(
            "SELECT id,state,resource_uid,prepare_pid,apply_writes FROM commands ORDER BY id"
        ).fetchall()
        owner = c.execute("SELECT fence,deleted FROM owner").fetchone()
    with closing(connect(Path(root) / "remote.sqlite")) as c:
        resources = c.execute(
            "SELECT command,hash,uid FROM resources ORDER BY command"
        ).fetchall()
    return {"commands": rows, "owner": owner, "resources": resources}


def child(root, *extra):
    # Foreground child is this exact lab only; no arbitrary executable or target.
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        timeout=20,
    )


def demo(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    results = []
    for point in CRASH:
        case = root / point
        initialize(case)
        crashed = child(case, "--fault", point)
        if crashed.returncode != CRASH[point] or crashed.stdout:
            raise RuntimeError("crash injection failed")
        before = inspect(case)
        recovery = child(case)
        if recovery.returncode:
            raise RuntimeError("recovery failed: " + recovery.stderr)
        normal = json.loads(recovery.stdout)
        again = child(case)
        if again.returncode:
            raise RuntimeError("idempotent retry failed")
        assert json.loads(again.stdout)["uid"] == normal["uid"]
        snapshot = inspect(case)
        row = snapshot["commands"][0]
        assert len(snapshot["commands"]) == len(snapshot["resources"]) == row[4] == 1
        assert row[2] == snapshot["resources"][0][2] == normal["uid"]
        assert row[3] != normal["pid"]
        results.append(
            {
                "fault": point,
                "crash_exit": crashed.returncode,
                "state_before_recovery": before["commands"][0][1],
                "resources_before_recovery": len(before["resources"]),
                "apply_writes_before_recovery": before["commands"][0][4],
                "recovered_state": row[1],
                "different_recovery_process": True,
                "apply_writes": row[4],
                "resource_count": len(snapshot["resources"]),
            }
        )
    case = root / "fence"
    initialize(case)
    stopped = child(case, "--lose-fence")
    assert stopped.returncode == 2 and not stopped.stdout
    before = inspect(case)
    assert before["commands"][0][1] == "prepared" and len(before["resources"]) == 1
    resumed = child(case, "--fence", "2")
    assert resumed.returncode == 0
    results.append(
        {
            "fault": "owner_changed_after_effect",
            "old_owner_exit": 2,
            "effect_exists_with_original_command": True,
            "new_owner_recovered": inspect(case)["commands"][0][1] == "applied",
        }
    )
    return {
        "experiments": results,
        "actual_process_exit_and_local_sqlite_reopen": True,
        "external_resource_service": "local durable FAKE SQLite service",
        "production_MySQL_Kubernetes_or_power_loss_verified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--fault", choices=tuple(CRASH))
    p.add_argument("--fence", type=int, default=1)
    p.add_argument("--lose-fence", action="store_true")
    a = p.parse_args()
    try:
        result = recover(a.root, COMMAND, PAYLOAD, a.fence, a.fault, a.lose_fence)
    except (ValueError, sqlite3.Error):
        print("lab operation blocked or unavailable", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
