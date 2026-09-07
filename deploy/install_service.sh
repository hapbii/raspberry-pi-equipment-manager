#!/usr/bin/env bash
set -euo pipefail

ALLOW_MOCK=()
CHECK_ONLY=false
for argument in "$@"; do
  case "$argument" in
    --allow-mock) ALLOW_MOCK=(--allow-mock) ;;
    --check) CHECK_ONLY=true ;;
    --help|-h)
      echo "사용법: sudo bash deploy/install_service.sh [--allow-mock] [--check]"
      echo "--allow-mock: 모델 없이 현재 mock 설정으로 웹 확인용 설치"
      echo "--check: 설정과 권한만 확인 (서비스 변경·실행 없음)"
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
for dependency in runuser systemctl systemd-analyze; do
  command -v "$dependency" >/dev/null || { echo "$dependency 명령이 필요합니다." >&2; exit 1; }
done

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_USER="$SUDO_USER"
APP_GROUP="$(id -gn "$APP_USER")"
UNIT=equipment-manager.service
TARGET="/etc/systemd/system/$UNIT"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  echo "$APP_DIR/.venv/bin/python이 없습니다. 프로젝트의 가상환경을 먼저 준비하세요." >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d /etc/systemd/system/.equipment-manager-install.XXXXXX)"
cleanup() {
  rm -f -- "$STAGING_DIR/$UNIT"
  rmdir -- "$STAGING_DIR"
}
trap cleanup EXIT
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" \
  "$APP_DIR/deploy/service_config.py" --app-dir "$APP_DIR" \
  --user "$APP_USER" --group "$APP_GROUP" "${ALLOW_MOCK[@]}" > "$STAGING_DIR/$UNIT"
systemd-analyze verify "$STAGING_DIR/$UNIT"
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
echo "서비스 실행 및 부팅 자동 실행 설정 완료."
echo "상태 확인: sudo systemctl status $UNIT --no-pager -l"
echo "이후 .env 수정은 sudo systemctl restart $UNIT 로 반영합니다."
echo "GitHub 코드는 부팅 시 자동 업데이트하지 않습니다."
