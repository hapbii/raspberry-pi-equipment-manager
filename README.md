# AI 기반 실습 기자재 관리 시스템

Raspberry Pi 4B 2GB와 카메라로 기자재의 **종류**를 YOLO로 인식하고, 대여·반납 수량을 학교 내부 웹사이트에서 확인하는 프로젝트입니다. 개별 기자재의 고유번호는 구분하지 않습니다.

## 구현된 기능

- 공개 현황판: 종류별 전체·대여 중·사용 가능 수량, 장치 온라인 상태
- 스테이션 PIN 로그인 후 YOLO 인식, 결과 확인, 대여·반납 처리
- 학생별 미반납과 재고 범위를 DB 트랜잭션으로 검사
- 관리자 기자재·수량 관리, 거래 취소·검색, CSV 내보내기
- Picamera2/USB 카메라와 PyTorch/NCNN YOLO 모델 지원
- 모델·카메라 재사용, 동시 추론 방지, 스트리밍 결과 해제, RSS 관측
- GPIO LED·부저를 고정 worker 하나로 처리
- 실제 장치 사전 점검, 반복 추론 메모리 검사, SQLite 백업
- heartbeat와 systemd 부팅 자동 실행

> 저장소에는 학습된 모델이 없습니다. 실제 인식에는 직접 학습한 `best.pt` 또는 `best_ncnn_model`이 필요합니다.

## 구조

```text
equipment_manager/
  routes/                 공개·스테이션·관리자 라우트
  vision/
    camera.py             지속형 Picamera2/OpenCV 카메라
    detector.py           Mock/YOLO와 다중 프레임 투표
    service.py            단일 추론 잠금·메모리·수명주기
  config.py               환경변수
  db.py                   SQLite
  inventory.py            재고·거래 규칙
  hardware.py             GPIO 피드백
  runtime.py              heartbeat와 만료 데이터 정리
deploy/
  equipment-manager.service
  install_service.sh
scripts/
  create_env.py           비밀 설정 생성
  capture_samples.py      Pi 카메라 학습 사진 수집
  pi_diagnostics.py       실제 모델·카메라 종합 점검
  memory_soak_test.py     실제 반복 추론 RSS 검사
  network_info.py         내부망 주소 확인
  backup_db.py            DB 백업
training/                 Colab 노트북과 data.yaml 예시
tests/                    임시 DB·가짜 장치 자동 테스트
```

## Raspberry Pi에서 실제로 실행하기

아래가 최종 장비에서 실행할 순서입니다. Raspberry Pi OS Bookworm 64-bit를 권장합니다.

### 1. 카메라와 시스템 확인

카메라 케이블은 전원을 끈 상태에서 연결합니다. 부팅 후 실행합니다.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3-venv python3-picamera2 python3-opencv rpicam-apps
rpicam-still -o camera-test.jpg
```

`camera-test.jpg`가 정상이어야 웹 프로그램도 카메라를 사용할 수 있습니다. USB 카메라는 `ls -l /dev/video*`로 장치 번호를 확인합니다.

### 2. 저장소와 가상환경 설치

저장소가 비공개이므로 GitHub 로그인 또는 deploy key가 필요합니다.

```bash
cd /opt
sudo git clone https://github.com/hapbii/raspberry-pi-equipment-manager.git
sudo chown -R "$USER":"$USER" /opt/raspberry-pi-equipment-manager
cd /opt/raspberry-pi-equipment-manager

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-pi.txt
python scripts/create_env.py
```

`--system-site-packages`는 Raspberry Pi OS의 Picamera2/libcamera 모듈을 가상환경에서 사용하기 위해 필요합니다.

### 3. 학습 모델 복사

다음 중 하나로 배치합니다.

```text
models/best.pt

models/best_ncnn_model/
  model.ncnn.bin
  model.ncnn.param
  metadata.yaml
```

Windows PC에서 Pi로 NCNN 모델을 복사하는 예시입니다.

```powershell
scp -r models\best_ncnn_model <PI_USER>@<PI_IP>:/opt/raspberry-pi-equipment-manager/models/
```

Ultralytics는 ARM CPU에서 NCNN을 성능 선택지로 안내합니다. 직접 학습한 모델은 정확도와 속도를 모두 비교한 뒤 결정합니다.

### 4. 실제 모드 설정

```bash
nano .env
```

공식 Pi 카메라와 NCNN 모델 기준 권장 시작값입니다.

```dotenv
DETECTOR_MODE=yolo
YOLO_MODEL_PATH=models/best_ncnn_model
YOLO_IMAGE_SIZE=320
YOLO_CONFIDENCE=0.60
YOLO_MIN_VOTES=3
YOLO_FRAME_COUNT=5
YOLO_MAX_DETECTIONS=5
INFERENCE_THREADS=2
GC_INTERVAL_SCANS=20

CAMERA_BACKEND=picamera2
CAMERA_WIDTH=640
CAMERA_HEIGHT=480
CAMERA_BUFFER_COUNT=2
CAMERA_WARMUP_SECONDS=0.5

YOLO_CLASS_ALIASES='{"multimeter":"멀티미터","arduino":"아두이노","breadboard":"브레드보드"}'
MEMORY_WARNING_MB=1200
GPIO_ENABLED=false
```

별칭의 왼쪽은 학습 `data.yaml` 클래스명, 오른쪽은 관리자 화면의 기자재명입니다. 바깥쪽 작은따옴표도 유지해야 systemd에서 JSON의 큰따옴표가 보존됩니다. 이름이 정확히 일치해야 재고와 연결됩니다. `best.pt`는 `YOLO_MODEL_PATH=models/best.pt`로 바꿉니다.

USB 카메라는 다음 설정을 사용합니다.

```dotenv
CAMERA_BACKEND=opencv
CAMERA_INDEX=0
```

### 5. 모델·카메라 사전 점검

기자재 하나를 카메라 앞에 놓고 실행합니다.

```bash
cd /opt/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/pi_diagnostics.py
```

모델 로딩, 카메라 해상도, 감지 결과, 실행 시간과 RSS가 출력됩니다. 물체가 없어도 프레임 촬영과 모델 추론이 성공하면 장치 점검은 통과합니다.

### 6. 반복 추론과 메모리 검사

같은 기자재를 놓은 채 먼저 50회, 최종 배포 전에는 200회 이상 확인합니다.

```bash
python scripts/memory_soak_test.py --scans 50 --interval 0.3 --max-growth-mb 120
python scripts/memory_soak_test.py --scans 200 --interval 0.5 --max-growth-mb 120
```

스크립트는 모델·카메라를 예열한 뒤 기준 RSS를 잡으므로 최초 모델 로딩 메모리를 누수로 계산하지 않습니다. 종료 RSS 증가량이 계속 커지거나 기준을 넘으면 배포를 중단하고 전체 출력을 확인합니다.

### 7. 웹 서버 수동 실행

```bash
MALLOC_ARENA_MAX=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
python -m waitress --listen=0.0.0.0:8080 --threads=2 wsgi:app
```

다른 터미널에서 주소를 봅니다.

```bash
cd /opt/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/network_info.py
```

같은 네트워크의 PC나 스마트폰에서 `http://<PI_IP>:8080`을 엽니다. 종료는 서버 터미널의 `Ctrl+C`입니다.

2GB Pi에서 worker 프로세스를 여러 개 띄우면 프로세스마다 모델이 복제됩니다. 이 프로젝트는 **프로세스 1개, Waitress 스레드 2개, 동시 추론 1개**를 전제로 합니다.

### 8. 부팅 자동 실행

수동 실행을 확인한 뒤 설치합니다.

```bash
sudo bash deploy/install_service.sh
sudo systemctl status equipment-manager.service
```

설치기가 현재 사용자·저장소 경로를 적용하고 `.env`를 root 전용 `/etc/equipment-manager.env`로 복사합니다. 서비스는 수치 연산 스레드를 제한하며 메모리 완화 기준 1300MB, 강제 상한 1600MB, 작업 수 상한 64를 적용합니다.

로그와 업데이트:

```bash
journalctl -u equipment-manager.service -f

cd /opt/raspberry-pi-equipment-manager
git pull
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
python -m unittest discover -s tests -v
sudo bash deploy/install_service.sh
```

서비스 제거 시 설정 백업 `/etc/equipment-manager.env`는 남겨 둡니다.

```bash
sudo systemctl disable --now equipment-manager.service
sudo rm /etc/systemd/system/equipment-manager.service
sudo systemctl daemon-reload
```

## 학습 사진을 Pi 카메라로 수집하기

한 종류만 촬영 구역에 두고 실행합니다.

```bash
source .venv/bin/activate
python scripts/capture_samples.py multimeter --count 250 --interval 0.5
python scripts/capture_samples.py arduino --count 250 --interval 0.5
python scripts/capture_samples.py breadboard --count 250 --interval 0.5
```

사진은 `datasets/raw/<클래스명>/`에 저장되며 Git에 올라가지 않습니다. 각도·거리·배경·조명·일부 가림을 바꿉니다. 같은 연속 촬영 묶음을 train과 val 양쪽에 나누지 않습니다.

`training/dataset_example.yaml`과 Colab 노트북을 사용해 라벨링 데이터로 학습합니다. 처음에는 3~5종, 종류당 200~500장으로 시작하고 실제 카메라 설치 위치 사진을 반드시 포함합니다.

## Windows에서 웹 기능만 시험하기

```powershell
git clone https://github.com/hapbii/raspberry-pi-equipment-manager.git
cd raspberry-pi-equipment-manager
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\create_env.py
python -m waitress --listen=0.0.0.0:8080 --threads=2 wsgi:app
```

기본값은 `DETECTOR_MODE=mock`입니다. `http://127.0.0.1:8080`에서 카메라 없이 업무 흐름을 확인할 수 있습니다.

## 주소와 권한

| 주소 | 권한 | 기능 |
|---|---|---|
| `/` | 공개 | 재고와 장치 상태 |
| `/station/login` | 공개 | 스테이션 PIN 로그인 |
| `/scan` | 스테이션 | 인식과 대여·반납 |
| `/admin/login` | 공개 | 관리자 로그인 |
| `/admin` | 관리자 | 미반납·거래·재고 관리 |
| `/admin/export.csv` | 관리자 | 거래 CSV |
| `/api/status` | 공개 | 현황·RSS·추론 상태 JSON |
| `/healthz` | 공개 | 서버·DB 검사 |

공개 화면에는 학번을 표시하지 않습니다.

## 데이터, GPIO, 네트워크

첫 실행 시 `instance/equipment.db`가 생성됩니다. `DEFAULT_EQUIPMENT`와 `DEFAULT_QUANTITY`는 최초 생성 때만 적용됩니다. 백업은 다음 명령으로 `backups/`에 만듭니다.

```bash
python scripts/backup_db.py
```

GPIO 기본 BCM 핀은 초록 LED 17, 빨간 LED 27, 부저 22입니다. 저항과 전압을 확인한 뒤 활성화합니다.

```dotenv
GPIO_ENABLED=true
GPIO_GREEN_PIN=17
GPIO_RED_PIN=27
GPIO_BUZZER_PIN=22
```

학교 내부라도 학생 Wi-Fi, 교사용 Wi-Fi, 유선망이 다른 VLAN이면 서로 접속하지 못합니다. 같은 실습실, 다른 교실·층, 학생 Wi-Fi, 교사용 Wi-Fi, 유선 PC에서 각각 시험합니다. 안 되면 전산 담당자에게 Pi 고정 IP/DHCP 예약과 내부망 사이 TCP 8080 허용을 요청합니다. Pi를 인터넷에 직접 공개하지 않습니다.

## 보안과 자동 테스트

- `.env`, 실제 DB, 사진, 모델은 Git에 올리지 않습니다.
- 디버그 서버 대신 Waitress/systemd를 사용합니다.
- HTTPS가 실제 구성된 경우에만 `SESSION_COOKIE_SECURE=true`로 바꿉니다.
- 외부 접속은 학교가 승인한 중앙 서버나 VPN을 사용합니다.

```bash
python -m compileall -q equipment_manager scripts tests wsgi.py
python -m unittest discover -s tests -v
```

단위 테스트는 임시 DB와 가짜 카메라·YOLO 결과를 사용합니다. 실제 하드웨어는 Pi에서 진단·반복 검사로 별도 검증해야 합니다.

## 문제 해결

### Picamera2 또는 카메라 오류

```bash
sudo apt install -y python3-picamera2
rpicam-still -o camera-test.jpg
sudo systemctl restart equipment-manager.service
```

가상환경이 `--system-site-packages`인지, 다른 프로세스가 카메라를 점유하지 않는지 확인합니다.

### 모델 또는 클래스 연결 오류

```bash
ls -la models
grep YOLO_MODEL_PATH .env
```

상대 모델 경로는 프로젝트 루트 기준입니다. `YOLO_CLASS_ALIASES`의 JSON, 대소문자, 공백과 관리자 기자재명을 확인합니다. `.env` 수정 후 systemd에는 `sudo bash deploy/install_service.sh`로 다시 반영합니다.

### 메모리 증가

```bash
python scripts/memory_soak_test.py --scans 200 --interval 0.5
curl http://127.0.0.1:8080/healthz
journalctl -u equipment-manager.service -n 200 --no-pager
```

서버가 한 프로세스인지 확인합니다. 필요하면 `YOLO_FRAME_COUNT=3`, `YOLO_IMAGE_SIZE=320`, 카메라 `640x480` 이하로 비교합니다.

### 다른 교실에서 접속 불가 또는 재부팅 후 실패

같은 네트워크에서 되고 다른 곳에서만 안 되면 학교 방화벽/VLAN 문제일 가능성이 큽니다. 서비스 문제는 다음으로 확인합니다.

```bash
sudo systemctl status equipment-manager.service
journalctl -u equipment-manager.service -n 100 --no-pager
```

## 참고 문서

- [Ultralytics 예측 모드와 stream 옵션](https://docs.ultralytics.com/modes/predict/)
- [Ultralytics Raspberry Pi 가이드](https://docs.ultralytics.com/guides/raspberry-pi/)
- [Ultralytics NCNN 통합](https://docs.ultralytics.com/integrations/ncnn/)
- [Raspberry Pi Picamera2 매뉴얼](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)

## 실물 배포 전에 남은 작업

- 실제 기자재 촬영·라벨링과 Colab 학습
- Pi에서 `best.pt`와 NCNN 정확도·속도 비교
- 실제 위치에서 오인식/미검출 시험과 200회 메모리 검사
- GPIO 실물 배선, 학교 고정 IP와 교실 간 접속 확인
- 실제 전체 수량 입력과 운영 담당자 지정
