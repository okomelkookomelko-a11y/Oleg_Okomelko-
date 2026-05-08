#!/usr/bin/env python3
"""
Git Relay: reads cmds/pending.json, executes command, writes cmds/result.json
Runs every 30 seconds via systemd timer.
"""
import os, subprocess, base64, json, requests
from datetime import datetime

GH_TOKEN = os.getenv("GH_TOKEN")
REPO = os.getenv("GH_REPO")
HEADERS = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
API = f"https://api.github.com/repos/{REPO}/contents"

def get_file(path):
    r = requests.get(f"{API}/{path}", headers=HEADERS)
    if r.status_code == 200:
        d = r.json()
        return base64.b64decode(d["content"]).decode().strip(), d["sha"]
    return None, None

def put_file(path, content, sha, msg):
    payload = {"message": msg, "content": base64.b64encode(content.encode()).decode()}
    if sha:
        payload["sha"] = sha
    r = requests.put(f"{API}/{path}", headers=HEADERS, json=payload)
    return r.status_code in (200, 201)

def get_sha_only(path):
    r = requests.get(f"{API}/{path}", headers=HEADERS)
    return r.json().get("sha") if r.status_code == 200 else None

def run_cmd(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd="/home/bot/my-bot")
        out = (r.stdout + r.stderr).strip()
        return out[:8000] if out else "(no output)", r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 1
    except Exception as e:
        return f"ERROR: {e}", 1

def main():
    raw, sha = get_file("cmds/pending.json")
    if not raw:
        return
    try:
        task = json.loads(raw)
    except json.JSONDecodeError:
        return

    task_id = task.get("id", "")
    cmd = task.get("cmd", "")
    if not cmd or task.get("status") in ("done", "running"):
        return

    # Mark running immediately to prevent re-execution by concurrent timer instances
    task["status"] = "running"
    put_file("cmds/pending.json", json.dumps(task, ensure_ascii=False, indent=2),
             sha, f"running: {task_id}")
    _, sha = get_file("cmds/pending.json")  # refresh sha after update

    print(f"[{datetime.now()}] id={task_id} cmd={cmd}")
    timeout = task.get("timeout", 60)
    output, code = run_cmd(cmd, timeout=timeout)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Write result
    result = {"id": task_id, "cmd": cmd, "output": output,
              "exit_code": code, "executed_at": ts, "status": "done"}
    result_sha = get_sha_only("cmds/result.json")
    put_file("cmds/result.json", json.dumps(result, ensure_ascii=False, indent=2),
             result_sha, f"result: {task_id}")

    # Mark pending as done
    task["status"] = "done"
    put_file("cmds/pending.json", json.dumps(task, ensure_ascii=False, indent=2),
             sha, f"done: {task_id}")

if __name__ == "__main__":
    main()
