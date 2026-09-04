#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "sudo bash deploy/install_service.sh 로 실행하세요."
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-}"

if [[ -z "${APP_USER}" || "${APP_USER}" == "root" ]]; then
  echo "일반 사용자 계정에서 sudo로 실행해야 합니다."
  exit 1
fi

APP_GROUP="$(id -gn "${APP_USER}")"
TEMPLATE="${APP_DIR}/deploy/equipment-manager.service"
TARGET="/etc/systemd/system/equipment-manager.service"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "${APP_DIR}/.env 파일이 없습니다. 먼저 python scripts/create_env.py 를 실행하세요."
  exit 1
fi

if [[ ! -x "${APP_DIR}/.venv/bin/waitress-serve" ]]; then
  echo "가상환경에 waitress가 없습니다. requirements-pi.txt 설치를 먼저 완료하세요."
  exit 1
fi

install -m 600 -o root -g root "${APP_DIR}/.env" /etc/equipment-manager.env
sed \
  -e "s|__USER__|${APP_USER}|g" \
  -e "s|__GROUP__|${APP_GROUP}|g" \
  -e "s|__APP_DIR__|${APP_DIR}|g" \
  "${TEMPLATE}" > "${TARGET}"

systemctl daemon-reload
systemctl enable --now equipment-manager.service
echo "설치 완료: systemctl status equipment-manager.service"
