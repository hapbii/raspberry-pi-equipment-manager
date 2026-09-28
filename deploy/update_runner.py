"""Root-owned systemd worker. Never execute checkout code with root privileges."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


UNIT = "equipment-manager.service"
STATUS = Path("/var/lib/equipment-manager-update/status.json")


def run_command(args, *, cwd=None, timeout=60):
    # Bound Git/SSH child processes too, so a hung network cannot leave a
    # background writer racing the restart after the parent times out.
    with subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace",
                          start_new_session=True) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        if process.returncode:
            # Detailed output is for the system journal, not the public web UI.
            print(output, flush=True)
            raise RuntimeError("command failed")
        return output.strip()


def wait_for_web(timeout=30):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8080/healthz", timeout=2) as response:
                if response.status == 200 and json.load(response).get("ok") is True:
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError("web health check failed")


def save_status(data):
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATUS)


def update(app_dir: Path, user: str, *, allow_mock=False):
    app_dir = app_dir.resolve(strict=True)
    prefix = ["/usr/sbin/runuser", "-u", user, "--", "/usr/bin/env",
              "GIT_TERMINAL_PROMPT=0", "GIT_SSH_COMMAND=ssh -oBatchMode=yes -oConnectTimeout=15"]

    def as_user(*args, timeout=60):
        return run_command([*prefix, *map(str, args)], cwd=app_dir, timeout=timeout)

    def git(*args, timeout=60):
        return as_user("/usr/bin/git", *args, timeout=timeout)

    report = {"state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "message": "업데이트를 시작했습니다. 완료 결과를 기다리는 중입니다."}
    save_status(report)
    stopped = False
    stage = "프로젝트 확인"
    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != app_dir:
            raise RuntimeError("not repository root")
        if git("branch", "--show-current") != "main":
            raise RuntimeError("main branch required")
        if git("status", "--porcelain"):
            raise RuntimeError("local changes must be resolved first")
        report["before"] = git("rev-parse", "HEAD")
        stage = "프로그램 중지"
        stopped = True  # A timed-out stop may still have reached systemd.
        run_command(["/usr/bin/systemctl", "stop", UNIT])
        time.sleep(2)
        stage = "DB 백업"
        python = app_dir / ".venv/bin/python"
        as_user(python, app_dir / "scripts/backup_db.py")
        stage = "Git 업데이트"
        git("pull", "--ff-only", "origin", "main", timeout=180)
        report["after"] = git("rev-parse", "HEAD")
        if report["after"] != git("rev-parse", "FETCH_HEAD"):
            raise RuntimeError("local commits differ from origin/main; resolve them over SSH")
        stage = "실행 설정 확인"
        as_user(python, app_dir / "serve.py", "--check", *(["--allow-mock"] if allow_mock else []))
        time.sleep(2)
        stage = "프로그램 재시작"
        run_command(["/usr/bin/systemctl", "start", UNIT])
        wait_for_web()
        stopped = False
        report.update(state="success", message="업데이트와 프로그램 재시작을 완료했습니다.")
        result = 0
    except Exception as exc:
        print(f"Update failed during {stage}: {type(exc).__name__}: {exc}", flush=True)
        message = f"{stage} 단계에서 실패했습니다. SSH에서 업데이트 로그를 확인해 주세요."
        if stopped:
            try:
                run_command(["/usr/bin/systemctl", "start", UNIT])
                wait_for_web()
                message += " 웹서버는 다시 실행되었습니다."
            except Exception:
                message += " 웹서버 복구도 확인하지 못했습니다. SSH에서 직접 점검해 주세요."
        report.update(state="failed", message=message)
        result = 1
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_status(report)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--allow-mock", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0 or args.user == "root":
        parser.error("Run only through the installed root-owned update service with a non-root app user.")
    return update(args.app_dir, args.user, allow_mock=args.allow_mock)


if __name__ == "__main__":
    raise SystemExit(main())
