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

DETECTOR_MODE="$(sed -n 's/^[[:space:]]*DETECTOR_MODE[[:space:]]*=[[:space:]]*//p' "${APP_DIR}/.env" | tail -n 1 | tr -d '\r' | xargs)"
if [[ "${DETECTOR_MODE}" != "yolo" ]]; then
  echo ".env의 DETECTOR_MODE=yolo 설정을 완료해야 실제 서비스로 설치할 수 있습니다."
  exit 1
fi

MODEL_PATH="$(sed -n 's/^[[:space:]]*YOLO_MODEL_PATH[[:space:]]*=[[:space:]]*//p' "${APP_DIR}/.env" | tail -n 1 | tr -d '\r')"
MODEL_PATH="${MODEL_PATH#\'}"
MODEL_PATH="${MODEL_PATH%\'}"
MODEL_PATH="${MODEL_PATH#\"}"
MODEL_PATH="${MODEL_PATH%\"}"
if [[ -z "${MODEL_PATH}" ]]; then
  echo ".env의 YOLO_MODEL_PATH에 실제 모델 파일 또는 NCNN 폴더를 입력하세요."
  exit 1
fi
if [[ "${MODEL_PATH}" != /* ]]; then
  MODEL_PATH="${APP_DIR}/${MODEL_PATH}"
fi
if [[ ! -e "${MODEL_PATH}" ]]; then
  echo "YOLO 모델을 찾을 수 없습니다: ${MODEL_PATH}"
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
