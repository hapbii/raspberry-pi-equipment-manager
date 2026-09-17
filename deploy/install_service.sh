#!/usr/bin/env bash
set -euo pipefail

ALLOW_MOCK=()
POWER_OPTIONS=()
ENABLE_POWEROFF=false
CHECK_ONLY=false
for argument in "$@"; do
  case "$argument" in
    --allow-mock) ALLOW_MOCK=(--allow-mock) ;;
    --enable-poweroff) ENABLE_POWEROFF=true; POWER_OPTIONS=(--enable-poweroff) ;;
    --check) CHECK_ONLY=true ;;
    --help|-h)
      echo "사용법: sudo bash deploy/install_service.sh [--allow-mock] [--enable-poweroff] [--check]"
      echo "--allow-mock: 모델 없이 현재 mock 설정으로 웹 확인용 설치"
      echo "--check: 설정과 권한만 확인 (서비스 변경·실행 없음)"
      echo "--enable-poweroff: 개발자 화면의 라파 종료·프로그램만 종료 허용 (설치 중에는 종료하지 않음)"
      exit 0 ;;
    *) echo "알 수 없는 옵션입니다. --help로 사용법을 확인하세요." >&2; exit 1 ;;
  esac
done

if [[ "$EUID" -ne 0 || -z "${SUDO_USER:-}" || "$SUDO_USER" == root ]]; then
  echo "라즈베리파이의 일반 사용자 터미널에서 sudo bash deploy/install_service.sh 로 실행하세요." >&2
  exit 1
fi
if [[ ! -d /run/systemd/system ]]; then
  echo "systemd로 부팅한 Raspberry Pi/Linux에서 실행하세요." >&2
  exit 1
fi
for dependency in runuser systemctl systemd-analyze curl; do
  command -v "$dependency" >/dev/null || { echo "$dependency 명령이 필요합니다." >&2; exit 1; }
done

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_USER="$SUDO_USER"
APP_GROUP="$(id -gn "$APP_USER")"
UNIT=equipment-manager.service
TARGET="/etc/systemd/system/$UNIT"
POWER_TIMER=equipment-manager-poweroff.timer
POWER_SERVICE=equipment-manager-poweroff.service
STOP_TIMER=equipment-manager-stop.timer
STOP_SERVICE=equipment-manager-stop.service
POWER_RULE=50-equipment-manager-poweroff.rules
RULE_TARGET="/etc/polkit-1/rules.d/$POWER_RULE"
if "$ENABLE_POWEROFF"; then
  if [[ ! -x /usr/bin/systemctl || ! -d /etc/polkit-1/rules.d ]] || ! command -v pkaction >/dev/null; then
    echo "종료 기능에는 polkit이 필요합니다. Pi에서 sudo apt install polkitd 를 실행한 뒤 다시 설치하세요." >&2
    exit 1
  fi
  if ! pkaction --action-id org.freedesktop.systemd1.manage-units >/dev/null; then
    echo "systemd의 polkit 권한을 확인하지 못했습니다. polkit 설치 상태를 확인하세요." >&2
    exit 1
  fi
fi
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  echo "$APP_DIR/.venv/bin/python이 없습니다. 프로젝트의 가상환경을 먼저 준비하세요." >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d /etc/systemd/system/.equipment-manager-install.XXXXXX)"
cleanup() {
  rm -f -- "$STAGING_DIR/$UNIT" "$STAGING_DIR/$POWER_TIMER" "$STAGING_DIR/$POWER_SERVICE" "$STAGING_DIR/$POWER_RULE" "$STAGING_DIR/$STOP_TIMER" "$STAGING_DIR/$STOP_SERVICE"
  rmdir -- "$STAGING_DIR"
}
trap cleanup EXIT
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" \
  "$APP_DIR/deploy/service_config.py" --app-dir "$APP_DIR" \
  --user "$APP_USER" --group "$APP_GROUP" "${ALLOW_MOCK[@]}" "${POWER_OPTIONS[@]}" > "$STAGING_DIR/$UNIT"
systemd-analyze verify "$STAGING_DIR/$UNIT"
if "$ENABLE_POWEROFF"; then
  cp -- "$APP_DIR/deploy/$POWER_TIMER" "$STAGING_DIR/$POWER_TIMER"
  cp -- "$APP_DIR/deploy/$POWER_SERVICE" "$STAGING_DIR/$POWER_SERVICE"
  cp -- "$APP_DIR/deploy/$STOP_TIMER" "$STAGING_DIR/$STOP_TIMER"
  cp -- "$APP_DIR/deploy/$STOP_SERVICE" "$STAGING_DIR/$STOP_SERVICE"
  runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" \
    "$APP_DIR/deploy/service_config.py" --app-dir "$APP_DIR" \
    --user "$APP_USER" --group "$APP_GROUP" --poweroff-rule > "$STAGING_DIR/$POWER_RULE"
  systemd-analyze verify "$STAGING_DIR/$POWER_TIMER" "$STAGING_DIR/$POWER_SERVICE" "$STAGING_DIR/$STOP_TIMER" "$STAGING_DIR/$STOP_SERVICE"
fi
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" \
  "$APP_DIR/serve.py" --check "${ALLOW_MOCK[@]}"
echo "실행 계정: $APP_USER ($APP_GROUP)"
echo "프로젝트: $APP_DIR"
echo "설정 파일: $APP_DIR/.env"
if "$CHECK_ONLY"; then
  echo "사전 확인 완료. 서비스를 변경하지 않았습니다."
  exit 0
fi

if [[ -f "$TARGET" ]]; then
  BACKUP="$(mktemp /etc/systemd/system/equipment-manager.service.backup.XXXXXX)"
  cp -p -- "$TARGET" "$BACKUP"
  echo "기존 서비스 설정 백업: $BACKUP"
fi
install -m 644 -o root -g root "$STAGING_DIR/$UNIT" "$TARGET"
if "$ENABLE_POWEROFF"; then
  for power_file in "$POWER_TIMER" "$POWER_SERVICE" "$STOP_TIMER" "$STOP_SERVICE" "$POWER_RULE"; do
    if [[ "$power_file" == "$POWER_RULE" ]]; then
      power_target="$RULE_TARGET"
    else
      power_target="/etc/systemd/system/$power_file"
    fi
    if [[ -e "$power_target" ]]; then
      power_backup="$(mktemp "${power_target}.backup.XXXXXX")"
      cp -p -- "$power_target" "$power_backup"
      echo "기존 종료 설정 백업: $power_backup"
    fi
    install -m 644 -o root -g root "$STAGING_DIR/$power_file" "$power_target"
  done
  # Never enable/start either timer here: only a confirmed web POST starts them.
elif [[ -f "$RULE_TARGET" ]]; then
  # Reinstall without the option revokes this application's OS-level permission.
  power_backup="$(mktemp "${RULE_TARGET}.disabled.XXXXXX")"
  mv -- "$RULE_TARGET" "$power_backup"
  echo "종료 권한 해제 (복구용 파일): $power_backup"
fi
systemctl daemon-reload
systemctl enable "$UNIT"
# enable --now alone does not restart an already running service.
if ! systemctl restart "$UNIT"; then
  echo "서비스 시작 실패. 아래 로그를 확인하세요." >&2
  journalctl -u "$UNIT" -n 30 --no-pager >&2
  exit 1
fi
sleep 2
if ! systemctl is-active --quiet "$UNIT"; then
  echo "서비스가 정상 실행되지 않았습니다. 수동 서버가 8080 포트를 사용 중인지도 확인하세요." >&2
  journalctl -u "$UNIT" -n 30 --no-pager >&2
  exit 1
fi
if ! curl --noproxy '*' --fail --silent --show-error --max-time 3 \
  --retry 8 --retry-connrefused --retry-delay 1 --retry-max-time 30 \
  http://127.0.0.1:8080/healthz >/dev/null || ! systemctl is-active --quiet "$UNIT"; then
  echo "웹·DB 응답 확인 실패. 설치 완료로 처리하지 않습니다. 아래 로그를 확인하세요." >&2
  journalctl -u "$UNIT" -n 30 --no-pager >&2
  exit 1
fi
echo "서비스 실행 및 부팅 자동 실행 설정 완료."
echo "상태 확인: sudo systemctl status $UNIT --no-pager -l"
echo "이후 .env 수정은 sudo systemctl restart $UNIT 로 반영합니다."
echo "GitHub 코드는 부팅 시 자동 업데이트하지 않습니다."
if "$ENABLE_POWEROFF"; then
  echo "개발자 시스템 화면에서 라파 종료 또는 프로그램만 종료를 요청할 수 있습니다. 실제 종료 시험은 모두 사용을 마친 뒤 진행하세요."
fi
