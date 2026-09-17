"""Request fixed, administrator-installed stop timers; never run a shell."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flask import current_app


SYSTEMCTL = "/usr/bin/systemctl"
POWER_TIMER = "equipment-manager-poweroff.timer"
PROGRAM_STOP_TIMER = "equipment-manager-stop.timer"


def _timer_available(timer: str) -> bool:
    # Viewing a page never starts a process or touches the camera.
    return bool(
        current_app.config.get("POWER_OFF_ENABLED", False)
        and sys.platform == "linux"
        and Path("/run/systemd/system").is_dir()
        and Path(SYSTEMCTL).is_file()
        and Path(f"/etc/systemd/system/{timer}").is_file()
    )


def poweroff_available() -> bool:
    return _timer_available(POWER_TIMER)


def program_stop_available() -> bool:
    # A manually launched server is not owned by the installed systemd unit.
    return bool(current_app.config.get("SYSTEMD_SERVICE_MANAGED", False)
                and _timer_available(PROGRAM_STOP_TIMER))


def schedule_poweroff() -> None:
    if not poweroff_available():
        raise RuntimeError("라파 종료 기능이 설치되지 않았거나 비활성화되어 있습니다.")
    _start_timer(POWER_TIMER)


def schedule_program_stop() -> None:
    if not program_stop_available():
        raise RuntimeError("프로그램 종료 기능을 설치하고 systemd 서비스로 실행해 주세요. 수동 실행은 터미널에서 Ctrl+C로 종료하세요.")
    _start_timer(PROGRAM_STOP_TIMER)


def _start_timer(timer: str) -> None:
    try:
        # systemd owns the delay, so there is no background Python thread to leak.
        # Starting an already active timer does not reset or duplicate it.
        result = subprocess.run(
            [SYSTEMCTL, "--no-ask-password", "start", timer],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("종료 요청 응답 시간이 초과되었습니다. 이미 예약됐을 수도 있으니 라파 상태를 확인하세요.") from exc
    except OSError as exc:
        raise RuntimeError("종료 요청을 실행하지 못했습니다. 서비스 설치 상태를 확인하세요.") from exc
    if result.returncode != 0:
        raise RuntimeError("종료 요청이 거부되었습니다. 종료 권한 설치와 systemd 로그를 확인하세요.")
