# AI 기반 실습 기자재 관리 시스템

Raspberry Pi 4B 2GB와 YOLO를 이용해 실습 기자재의 **큰 종류**를 인식하고, 종류별 대여·반납 수량을 학교 내부 웹사이트에서 조회하는 프로젝트입니다.

개별 기자재 고유번호는 구분하지 않습니다. 멀티미터, 아두이노, 브레드보드처럼 기자재 종류와 수량을 관리합니다.

## 주요 기능

- 공개 기자재 현황 대시보드와 5초 자동 갱신
- 종류별 전체·대여 중·사용 가능 수량
- 스테이션 PIN으로 보호된 대여·반납 화면
- 학번, 처리 구분, 수량 입력
- 객체 인식 결과 확인 후 한 번만 DB 반영
- 학생별 미반납 수량 검사
- 재고 음수, 전체 수량 초과 및 중복 거래 방지
- 관리자 로그인, 기자재 추가, 수량 보정
- 미반납 학생 집계와 거래 검색
- 거래 취소와 CSV 내보내기
- 장치 heartbeat와 온라인·오프라인 표시
- 카메라가 없어도 실행 가능한 모의 인식 모드
- YOLO PyTorch·NCNN 모델, Picamera2·USB 카메라 연결부
- GPIO LED·부저 피드백
- SQLite 백업과 systemd 부팅 자동 실행 예시

## 프로젝트 구조

```text
equipment_manager/
  __init__.py          Flask 애플리케이션 생성
  config.py            환경변수와 장치 설정
  db.py                SQLite 연결과 초기화
  inventory.py         재고·거래·미반납 처리
  detectors.py         Mock/YOLO 인식과 카메라 처리
  hardware.py          GPIO LED·부저 출력
  runtime.py           장치 heartbeat
  web.py               화면과 API 라우트
  templates/           HTML 화면
  static/              CSS와 JavaScript
training/
  YOLO_기자재_학습_Colab.ipynb
  dataset_example.yaml
deploy/
  equipment-manager.service
scripts/
  create_env.py        비밀값이 포함된 .env 생성
  network_info.py      학교 내부 접속 주소 확인
  backup_db.py         SQLite 안전 백업
  test_model_image.py  사진 한 장으로 YOLO 시험
tests/
  test_app.py
wsgi.py                Waitress/Gunicorn 실행 진입점
```

## 1. Windows PC에서 모의 실행

카메라와 YOLO 모델 없이 웹사이트와 대여·반납 기능부터 시험하는 방법입니다.

### 1-1. 준비물

- Windows 10 또는 11
- Python 3.11 이상
- Git
- PowerShell

Python 설치 시 `Add Python to PATH`를 선택합니다.

### 1-2. 저장소 받기

```powershell
git clone https://github.com/hapbii/raspberry-pi-equipment-manager.git
cd raspberry-pi-equipment-manager
```

### 1-3. 가상환경 만들기

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

PowerShell 명령줄 앞에 `(.venv)`가 표시되면 가상환경이 활성화된 상태입니다.

### 1-4. 환경설정 만들기

```powershell
python scripts\create_env.py
```

명령이 다음 파일과 값을 생성합니다.

- `.env`: 프로그램 설정 파일
- 관리자 비밀번호: 관리자 화면 접속용
- 스테이션 PIN: 대여·반납 화면 접속용

출력된 관리자 비밀번호와 PIN을 기록합니다. `.env`는 Git에 업로드되지 않습니다.

기본 `.env`의 `DETECTOR_MODE=mock`은 카메라 없이 기자재를 선택하여 인식 결과를 흉내 내는 모드입니다.

### 1-5. 서버 실행

```powershell
python -m waitress --listen=0.0.0.0:8080 --threads=4 wsgi:app
```

다음 메시지가 나오면 정상입니다.

```text
Serving on http://0.0.0.0:8080
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8080
```

서버를 종료할 때는 서버를 실행한 PowerShell에서 `Ctrl+C`를 누릅니다.

## 2. 모의 대여·반납 시험

### 대여

1. 상단의 `대여·반납` 메뉴를 누릅니다.
2. `create_env.py`가 출력한 스테이션 PIN으로 로그인합니다.
3. 학번을 입력합니다.
4. `대여`를 선택합니다.
5. 수량을 입력합니다.
6. 모의 인식 기자재를 선택합니다.
7. `객체 인식 시작`을 누릅니다.
8. 인식된 기자재와 신뢰도를 확인합니다.
9. `이 결과로 처리`를 누릅니다.
10. 현황 화면에서 사용 가능 수량이 감소했는지 확인합니다.

### 반납

같은 학번으로 `반납`을 선택하여 처리합니다. 해당 학생이 실제로 빌린 수량보다 많이 반납하려 하면 서버가 거래를 거부합니다.

### 관리자 기능

1. 상단의 `관리자` 메뉴를 누릅니다.
2. 생성된 관리자 비밀번호로 로그인합니다.
3. 기자재 종류 추가와 수량 보정을 시험합니다.
4. `현재 미반납`에서 학생별 미반납 수량을 확인합니다.
5. 거래를 취소하면 재고가 원래 방향으로 복구됩니다.
6. `CSV 내보내기`로 최근 기록을 저장할 수 있습니다.

## 3. URL과 권한

| 주소 | 권한 | 기능 |
|---|---|---|
| `/` | 공개 | 종류별 현재 수량과 장치 상태 |
| `/station/login` | 공개 | 인식 스테이션 PIN 로그인 |
| `/scan` | 스테이션 | 객체 인식과 대여·반납 처리 |
| `/admin/login` | 공개 | 관리자 로그인 |
| `/admin` | 관리자 | 미반납·거래·재고 관리 |
| `/admin/export.csv` | 관리자 | 거래 CSV 다운로드 |
| `/api/status` | 공개 | 현황 화면용 JSON API |
| `/healthz` | 공개 | 서버와 DB 동작 확인 |

일반 현황 화면에는 학생 이름이나 학번을 표시하지 않습니다.

## 4. 데이터베이스 초기화와 위치

처음 실행하면 `instance/equipment.db`가 자동 생성되고 다음 기자재가 각각 10개씩 등록됩니다.

- 멀티미터
- 아두이노
- 브레드보드

초기 항목은 `.env`에서 바꿀 수 있습니다.

```text
DEFAULT_EQUIPMENT=멀티미터,아두이노,브레드보드
DEFAULT_QUANTITY=10
```

이 값은 **DB가 처음 만들어질 때만** 적용됩니다. 이미 DB가 있다면 관리자 화면에서 종류와 수량을 수정합니다.

개발 DB를 처음부터 다시 만들고 싶다면 서버를 종료하고 `instance/equipment.db`를 백업한 뒤 삭제합니다. 다음 실행 시 새 DB가 생성됩니다.

백업:

```powershell
python scripts\backup_db.py
```

백업 파일은 `backups` 폴더에 만들어집니다.

## 5. 자동 테스트

```powershell
python -m unittest discover -s tests -v
```

테스트는 임시 DB와 모의 인식을 사용하므로 실제 `instance/equipment.db`를 변경하지 않습니다.

테스트 범위:

- 공개 대시보드와 상태 API
- 스테이션 인증과 CSRF 검사
- 대여·반납 및 학생별 미반납 수량
- 재고 부족과 잘못된 반납 거부
- 인식 토큰 중복 사용 방지
- 관리자 수량 보정과 거래 취소
- 기자재 추가, 검색, CSV 내보내기

## 6. YOLO 데이터셋 준비

권장 데이터셋 구조:

```text
equipment_dataset/
  data.yaml
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
```

처음에는 기자재 3~5종과 종류당 약 200~500장으로 시작합니다.

- 정면, 측면, 위쪽 등 각도를 다양하게 촬영합니다.
- 밝기, 거리, 배경을 바꿉니다.
- 실제 Raspberry Pi 카메라 설치 위치의 사진을 포함합니다.
- 같은 영상의 인접 프레임을 train과 val에 나누어 넣지 않습니다.
- 물체 전체가 포함되도록 bounding box 기준을 통일합니다.

`training/dataset_example.yaml`을 복사하여 클래스와 경로를 수정합니다.

```yaml
path: /content/equipment_dataset
train: images/train
val: images/val
test: images/test

names:
  0: multimeter
  1: arduino
  2: breadboard
```

## 7. Google Colab에서 YOLO 학습

1. `training/YOLO_기자재_학습_Colab.ipynb`를 Google Drive에 올립니다.
2. Colab에서 노트북을 엽니다.
3. `런타임 > 런타임 유형 변경 > T4 GPU`를 선택합니다.
4. 데이터셋을 Google Drive에 올립니다.
5. 노트북의 `DATA_YAML` 경로를 수정합니다.
6. 셀을 위에서 아래로 실행합니다.
7. 학습 후 confusion matrix와 실제 오인식 이미지를 확인합니다.
8. `best.pt`와 `best_ncnn_model.zip`을 내려받습니다.

Colab 메모리가 부족하면 `batch=16`을 `batch=8`로 낮춥니다.

## 8. PC에서 학습 모델 단일 이미지 시험

전체 YOLO 의존성을 설치합니다.

```powershell
python -m pip install -r requirements-pi.txt
```

모델과 시험 사진을 지정합니다.

```powershell
python scripts\test_model_image.py models\best.pt test_images\multimeter.jpg --imgsz 320 --conf 0.60
```

결과 이미지는 `runs/single-image-test`에 저장됩니다.

## 9. 실제 YOLO 모드 설정

`best.pt`를 다음 위치에 복사합니다.

```text
models/best.pt
```

`.env`를 수정합니다.

```text
DETECTOR_MODE=yolo
YOLO_MODEL_PATH=models/best.pt
YOLO_IMAGE_SIZE=320
YOLO_CONFIDENCE=0.60
YOLO_MIN_VOTES=3
YOLO_FRAME_COUNT=5
```

모델의 영문 클래스명과 DB의 한글 기자재명을 연결합니다.

```text
YOLO_CLASS_ALIASES={"multimeter":"멀티미터","arduino":"아두이노","breadboard":"브레드보드"}
```

클래스 별칭이 없거나 오타가 있으면 인식은 성공해도 DB 기자재와 연결되지 않습니다.

### NCNN 모델 사용

Colab에서 받은 압축을 풀어 다음처럼 배치합니다.

```text
models/best_ncnn_model/
  model.ncnn.bin
  model.ncnn.param
  metadata.yaml
```

`.env`를 수정합니다.

```text
YOLO_MODEL_PATH=models/best_ncnn_model
```

`best.pt`와 NCNN을 각각 시험하여 정확도와 응답 시간을 비교합니다.

## 10. Raspberry Pi 4B 설치

### 10-1. 권장 환경

- Raspberry Pi 4B RAM 2GB
- Raspberry Pi OS 64-bit Lite
- Raspberry Pi Camera 또는 USB 카메라
- 안정적인 5V 전원
- 가능하면 유선 LAN

### 10-2. 시스템 패키지 설치

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3-venv python3-picamera2 python3-opencv
```

### 10-3. 프로젝트 설치

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

비공개 저장소를 Pi에서 복제하려면 GitHub 인증 또는 deploy key가 필요합니다.

### 10-4. 카메라 확인

```bash
rpicam-hello -t 5000
```

미리보기가 나오지 않으면 웹 프로그램보다 카메라 연결과 케이블 방향을 먼저 확인합니다.

USB 카메라라면 `.env`를 다음처럼 바꿉니다.

```text
CAMERA_BACKEND=opencv
CAMERA_INDEX=0
```

공식 Raspberry Pi 카메라라면 다음 설정을 사용합니다.

```text
CAMERA_BACKEND=picamera2
```

### 10-5. 수동 실행 시험

```bash
source .venv/bin/activate
python -m waitress --listen=0.0.0.0:8080 --threads=4 wsgi:app
```

다른 기기에서 접속 주소를 확인합니다.

```bash
python scripts/network_info.py
```

## 11. 부팅 시 자동 실행

`deploy/equipment-manager.service`에서 다음 세 항목을 실제 사용자와 설치 경로에 맞게 수정합니다.

```ini
User=pi
Group=pi
WorkingDirectory=/opt/raspberry-pi-equipment-manager
ExecStart=/opt/raspberry-pi-equipment-manager/.venv/bin/waitress-serve --host=0.0.0.0 --port=8080 --threads=4 wsgi:app
```

환경설정을 시스템 위치로 복사합니다.

```bash
sudo cp .env /etc/equipment-manager.env
sudo chmod 600 /etc/equipment-manager.env
```

서비스를 등록합니다.

```bash
sudo cp deploy/equipment-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now equipment-manager
sudo systemctl status equipment-manager
```

실시간 로그:

```bash
journalctl -u equipment-manager -f
```

코드를 업데이트한 뒤:

```bash
cd /opt/raspberry-pi-equipment-manager
git pull
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
sudo systemctl restart equipment-manager
```

## 12. GPIO LED와 부저

BCM 번호 기준 기본 설정:

| 부품 | GPIO |
|---|---:|
| 초록 LED | 17 |
| 빨간 LED | 27 |
| 부저 | 22 |

저항과 전압을 실제 부품 규격에 맞게 연결한 후 `.env`를 수정합니다.

```text
GPIO_ENABLED=true
GPIO_GREEN_PIN=17
GPIO_RED_PIN=27
GPIO_BUZZER_PIN=22
```

인식 또는 거래 성공 시 초록 LED와 1회 부저, 실패 시 빨간 LED와 2회 부저가 동작합니다. GPIO 초기화에 실패하면 웹 기능은 유지되고 GPIO만 비활성화됩니다.

## 13. 학교 네트워크 배포 확인

학교 안에 있다고 해서 모든 기기가 같은 네트워크인 것은 아닙니다. 다음 환경은 서로 통신하지 못할 수 있습니다.

- 학생 Wi-Fi
- 교사용 Wi-Fi
- 교실 유선망
- 실습실 공유기
- 게스트 Wi-Fi

서버 실행 후 다음 장소에서 접속을 각각 시험합니다.

1. 라즈베리파이와 같은 실습실
2. 다른 교실
3. 다른 층
4. 학생 Wi-Fi 스마트폰
5. 교사용 Wi-Fi 기기
6. 유선 LAN PC

접속이 차단되면 학교 전산 담당자에게 다음을 요청합니다.

- Raspberry Pi 고정 IP 또는 DHCP 예약
- 필요한 내부망 사이의 TCP 8080 통신 허용
- 개인 장치 웹 서버 운영 허가

외부 인터넷에 Raspberry Pi의 포트를 직접 개방하지 마세요. 학교 밖에서도 접속해야 한다면 학교가 승인한 중앙 서버나 별도 호스팅 구성이 필요합니다.

## 14. 보안 설정

학교 배포 전 확인합니다.

- `.env`의 관리자 비밀번호와 스테이션 PIN 변경
- `.env` 파일 권한 제한
- Flask 개발 서버 대신 Waitress 또는 Gunicorn 사용
- 현황 화면에 학번·이름을 표시하지 않기
- 관리자 계정을 불필요하게 공유하지 않기
- 디버그 모드 사용 금지
- 라즈베리파이를 인터넷에 직접 공개하지 않기

HTTPS가 구성된 경우에만 다음 값을 사용합니다.

```text
SESSION_COOKIE_SECURE=true
```

학교 내부에서 HTTP로 시험하는 동안에는 `false`를 유지합니다.

## 15. 문제 해결

### `No module named flask`

가상환경을 활성화하고 의존성을 다시 설치합니다.

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### `YOLO 모델을 찾을 수 없습니다`

`.env`의 `YOLO_MODEL_PATH`와 실제 파일 또는 폴더 위치를 확인합니다.

### `모델 클래스가 DB 기자재와 일치하지 않습니다`

`YOLO_CLASS_ALIASES`의 영문 클래스명과 관리자 화면의 한글 기자재명을 확인합니다.

### 카메라를 열 수 없음

- 공식 카메라: `rpicam-hello -t 5000` 실행
- USB 카메라: `CAMERA_BACKEND=opencv` 확인
- 다른 프로그램이 카메라를 사용 중인지 확인
- 카메라 케이블 방향과 커넥터 잠금 확인

### 다른 교실에서 접속 불가

같은 교실에서 먼저 접속한 뒤 다른 네트워크 구역을 시험합니다. 같은 교실에서는 되고 다른 곳에서만 안 되면 방화벽 또는 VLAN 문제일 가능성이 높습니다.

### 재부팅 후 실행되지 않음

```bash
sudo systemctl status equipment-manager
journalctl -u equipment-manager -n 100 --no-pager
```

서비스 파일의 사용자명, 경로, 환경파일 위치를 확인합니다.

### 재고가 실제 수량과 다름

관리자 화면에서 실물 수량을 확인한 뒤 전체 수량과 사용 가능 수량을 보정합니다. 잘못된 거래는 삭제하지 말고 `취소`하여 기록을 남깁니다.

## 아직 실제 환경에서 해야 할 작업

- 실제 기자재 사진 수집과 라벨링
- Colab 모델 학습과 정확도 분석
- `best.pt`·NCNN 성능 비교
- 카메라 고정대와 단색 촬영 구역 제작
- Raspberry Pi GPIO 실물 배선
- 학교 네트워크 고정 IP와 교실 간 접속 허가
- 실제 기자재 전체 수량과 관리자 담당자 확정
