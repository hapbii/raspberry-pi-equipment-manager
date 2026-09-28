# AI 실습 기자재 대여·반납 시스템

라즈베리파이 카메라로 기자재 **종류**를 인식하고, 웹사이트에서 대여·반납과 현재 수량을 관리하는 학교 과제입니다. Raspberry Pi 4B RAM 2GB 한 대에 카메라, 웹 서버, DB를 연결합니다.

학생은 가입 승인 후 본인 학번으로 이용하고, 선생님은 기자재·학생·거래를 관리합니다. 개발자는 시스템 점검과 종료 기능까지 사용할 수 있습니다. **개별 물품의 고유번호를 구분하거나 사진 속 물품 개수를 자동으로 세지는 않습니다. 카메라 앞에 하나씩 놓고 웹 화면에서 한 번에 1개를 처리합니다.**

## 필요한 내용부터 찾기

| 지금 하려는 일 | 읽을 곳 |
|---|---|
| 처음부터 설치하기 | [1. 구성과 준비물](#overview) → [2. 라파 설치](#install) → [3. 계정·설정](#accounts) |
| 모델 없이 웹사이트 확인하기 | [4. 웹 확인과 수동 실행](#web) |
| 사진 찍고 PC로 가져오기 | [5. 촬영·PC 전송](#capture) |
| 사진에 박스 그리고 학습하기 | [6. 라벨링·Colab 학습](#labeling) |
| `best.pt`를 실제 인식에 적용하기 | [7. 모델 적용](#model) → [8. 실제 장치 검사](#diagnostics) |
| 전원을 켜면 자동 실행되게 하기 | [9. systemd와 종료](#service) |
| 웹 버튼으로 코드 업데이트하기 | [9-4. 업데이트·자동 재시작](#web-update) |
| 학생·선생님이 사용하는 방법 | [10. 대여·반납과 관리](#usage) |
| 다른 교실에서 접속이 안 될 때 | [11. 접속과 네트워크](#network) |
| 코드 업데이트·DB 백업·복구 | [12. 운영과 유지보수](#maintenance) |
| `.env` 항목을 바꾸고 싶을 때 | [13. 설정값 안내](#configuration) |
| 오류 해결 | [14. 문제 해결](#troubleshooting) |
| PC에서 개발·자동 테스트 | [15. 개발과 검증](#development) |
| 학교 운영 전 마지막 확인 | [16. 배포 확인 목록](#release) |

처음 만드는 경우의 순서는 **라파 준비 → 웹 확인 → 사진 촬영 → PC 전송·라벨링 → Colab 학습 → 모델 적용·검사 → 자동 실행 → 학교 현장 시험**입니다. 이미 설치된 라파에서는 OS나 `.env`, DB를 새로 만들지 말고 필요한 단계부터 진행하세요.

### 명령어를 어디에 입력하나요?

| 표시 | 실행 위치 |
|---|---|
| **PC PowerShell** | Windows에서 새로 연 PowerShell. `PS C:\...>`가 보임 |
| **라파 SSH 터미널** | PC에서 `ssh`로 접속한 뒤의 창. `pi30304@...:~ $`가 보임 |
| **`.env` 편집** | 프로젝트의 `.env` 파일 안에 입력. 터미널 명령이 아님 |
| **PC 브라우저 / 프로그램** | 주소창 또는 X-AnyLabeling 화면에서 작업 |

PC 화면에 열린 창이어도 SSH 접속 뒤에는 **라파에서** 명령이 실행됩니다. PC 명령은 별도 PowerShell 창을 열거나 SSH에서 `exit`로 나온 후 입력하세요. Python 코드가 든 파일은 더블클릭하지 않고 안내된 명령으로 실행합니다.

이 문서의 예시는 다음 환경을 사용합니다. 사용자·IP가 다르면 바꾸세요. IP는 네트워크가 바뀌면 달라질 수 있습니다.

| 항목 | 예시 |
|---|---|
| 라파 SSH 사용자 | `pi30304` |
| 라파 IP | `10.177.156.96` |
| 라파 프로젝트 | `/home/pi30304/raspberry-pi-equipment-manager` |
| PC 프로젝트 | `README.md`와 `scripts` 폴더가 있는 로컬 작업 폴더 |
| 웹 주소 | `http://10.177.156.96:8080` |

명령은 한 블록 안에서 위에서 아래로 실행합니다. 오류가 나면 해결한 뒤 다음 단계로 넘어가세요. 비밀번호 입력 시 글자나 별표가 표시되지 않는 것은 정상입니다.

<a id="overview"></a>
## 1. 구성과 준비물

```text
학교 PC·휴대전화의 브라우저
        │ HTTP :8080
        ▼
Raspberry Pi 4B 2GB
 ├─ Waitress: 웹 요청 수신
 ├─ Flask: 로그인·권한·대여·반납·관리 화면
 ├─ SQLite: 기자재·학생 계정·대여 기록
 ├─ 카메라 + YOLO: 기자재 종류 인식
 └─ GPIO LED·부저: 선택 사항

학습 준비: 라파 촬영 → PC 전송·180도 회전 → X-AnyLabeling
          → Google Colab 학습 → best.pt / NCNN → 라파
```

Flask는 웹 기능을 구현하고 Waitress가 운영용 웹 서버 역할을 합니다. 모든 사용자는 라파의 SQLite DB 하나를 공유합니다. PC마다 별도 DB를 복사하는 방식이 아닙니다.

| 준비물 | 용도 |
|---|---|
| Raspberry Pi 4B 2GB, 전원, microSD | 서버·인식 장치. 사진과 모델 저장 공간도 확보 |
| Raspberry Pi OS 64비트 | Python·카메라·systemd 실행. 모니터 없이 운영하면 Lite 사용 가능 |
| Pi 리본 케이블 카메라 또는 USB 카메라 | 실제 설치 위치에서 촬영·인식 |
| Windows PC, SSH, Python 3.10 이상 | 원격 접속, 사진 가져오기·회전 |
| PC의 Git | 코드 내려받기·업데이트 |
| X-AnyLabeling | PC 사진 라벨링. 기존 PC에는 4.0.6 설치됨 |
| Google Drive·Colab | 데이터셋 보관·GPU 학습 |
| 장치 간 통신이 가능한 네트워크 | SSH 22번, 웹 8080번 포트 사용 |

**모델 없이 가능한 일:** 웹 현황·회원가입·관리 화면 확인, 학습용 사진 촬영, PC 전송, 수동 라벨링. **실제 대여·반납 인식에는 학습 모델과 정상 카메라가 필요**하며 `mock`에서는 실제 거래를 진행하지 않습니다.

Pi 한 대 구성으로 설계되어 있습니다. 학교 어디서나 조회하려면 교실 간 네트워크 통신이 허용되어야 합니다. 웹 버튼을 누르면 **라파에 연결된 카메라**가 작동하며, 버튼을 누른 PC나 휴대전화 카메라를 사용하지 않습니다.

<a id="install"></a>
## 2. 라파 OS·카메라·프로젝트 설치

### 2-1. 처음 사용하는 라파만 OS 설치

**작업 위치: Windows PC의 Raspberry Pi Imager**

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/)에서 장치 `Raspberry Pi 4`, OS `Raspberry Pi OS Lite (64-bit)`, 대상 microSD를 선택합니다.
2. 사용자명·비밀번호, Wi-Fi·국가 `KR`, 시간대 `Asia/Seoul`, SSH 접속을 설정합니다. 이 문서는 사용자명 `pi30304` 예시를 사용합니다.
3. OS 기록은 대상 카드의 기존 내용을 지웁니다. 기존 운영 카드라면 재설치부터 시작하지 마세요.
4. 전원이 꺼진 상태에서 microSD와 카메라 케이블을 연결한 뒤 전원을 켭니다.

자세한 초기 설정은 [Raspberry Pi 공식 설치 안내](https://www.raspberrypi.com/documentation/computers/getting-started.html)를 참고하세요. 호스트 이름을 정했다면 `호스트이름.local`로 접속할 수도 있지만, 연결되지 않으면 공유기·라파에서 실제 IP를 확인합니다.

### 2-2. SSH 연결과 기본 패키지

**실행 위치: PC PowerShell**

```powershell
ssh pi30304@10.177.156.96
```

처음 접속 시 장치 정보를 확인하고 연결을 승인합니다. 이후 사용할 SSH 비밀번호와 웹 관리자 비밀번호는 서로 다른 계정의 값입니다.

**실행 위치: 라파 SSH 터미널**

```bash
sudo apt update
sudo apt install -y git curl sqlite3 python3-venv python3-picamera2 python3-opencv rpicam-apps
uname -m
hostname -I
timedatectl
```

64비트 OS의 `uname -m`은 보통 `aarch64`입니다. 날짜·시간대는 반납 기한 계산에도 사용합니다. 시간대가 다르면 라파에서 `sudo timedatectl set-timezone Asia/Seoul`로 맞춥니다.

### 2-3. 카메라 확인

촬영·인식 서버가 이미 켜져 있다면 먼저 종료하세요. 카메라는 한 프로그램씩 사용합니다.

**실행 위치: 라파 SSH 터미널 — Pi 리본 케이블 카메라**

```bash
rpicam-hello --list-cameras
rpicam-still --nopreview --timeout 2000 --output camera-test.jpg
ls -lh camera-test.jpg
```

`--nopreview`를 사용하므로 SSH에서 미리보기 창이 필요하지 않습니다. 파일을 PC로 복사해 초점·색상도 확인하세요. 명령 사용법은 [공식 카메라 안내](https://www.raspberrypi.com/documentation/computers/camera_software.html)를 참고하세요.

**실행 위치: PC PowerShell — 시험 사진을 PC 다운로드 폴더로 복사**

```powershell
scp pi30304@10.177.156.96:~/camera-test.jpg "$env:USERPROFILE\Downloads\camera-test.jpg"
```

USB 카메라는 `rpicam` 대신 OpenCV로 확인합니다. 라파에서 `ls -l /dev/video*`로 장치를 조회할 수 있지만, 모든 `/dev/video*`가 USB 카메라는 아닙니다. 프로젝트 설치 후 [촬영 단계](#capture)에서 `--backend opencv --camera-index 0`으로 한 장을 시험하세요.

### 2-4. 저장소와 가상환경 준비

**실행 위치: 라파 SSH 터미널 — 처음 설치할 때만**

```bash
cd ~
git clone https://github.com/hapbii/raspberry-pi-equipment-manager.git
cd raspberry-pi-equipment-manager
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-pi.txt
```

저장소는 공개되어 있어 일반 HTTPS 복제에 GitHub 토큰이 필요하지 않습니다. 이미 폴더가 있으면 다시 복제하지 말고 [업데이트 절차](#maintenance)를 따르세요.

`--system-site-packages`는 apt로 설치한 Picamera2·OpenCV를 가상환경에서 사용하기 위한 옵션입니다. 설치가 오래 걸릴 수 있습니다. 새 SSH 창을 열면 아래 두 명령으로 작업 위치와 Python 환경을 다시 맞춥니다.

**실행 위치: 라파 SSH 터미널 — 새 창에서 작업을 시작할 때**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
```

`(.venv)`가 보이면 가상환경이 활성화된 것입니다. 서비스는 `.venv/bin/python`을 직접 사용하므로 별도 활성화 명령 없이 실행됩니다. **PC용 `.venv`와 라파용 `.venv`는 서로 복사하지 않습니다.**

<a id="accounts"></a>
## 3. 설정 파일과 관리자 계정

### 3-1. 최초 생성 또는 기존 설정 유지

`.env.example`은 양식이고, 실제 실행 시 읽는 파일은 **프로젝트의 `.env`**입니다. 기존 `.env`가 있으면 아래 생성 명령을 건너뛰세요.

**실행 위치: 라파 SSH 터미널 — 프로젝트 폴더·가상환경, 최초 한 번**

```bash
python scripts/create_env.py
```

무작위 `SECRET_KEY`와 개발자·선생님 비밀번호를 생성하고 화면에 계정 정보를 표시합니다. 안전한 곳에 기록하세요. 파일이 이미 있으면 덮어쓰지 않습니다. 비밀번호가 포함된 `.env`는 GitHub 업로드 대상이 아닙니다.

이전 버전의 관리자 계정만 있는 `.env`라면 삭제하지 않고 아래 도구로 역할별 계정을 보완합니다. **실행 결과에 비밀번호가 표시**됩니다.

**실행 위치: 라파 SSH 터미널 — 이전 설정을 사용하는 경우만**

```bash
python scripts/setup_accounts.py
```

이미 있는 역할별 값은 유지합니다. 계정 변경은 `.env`의 `DEVELOPER_USERNAME`, `DEVELOPER_PASSWORD`, `TEACHER_USERNAME`, `TEACHER_PASSWORD`를 편집하고 서버를 재시작해 반영합니다. 선생님 계정은 공용 한 개이고, 학생 가입으로 관리자 계정을 만들 수 없습니다.

### 3-2. 설정 편집과 사전 검사

**실행 위치: 라파 SSH 터미널 — 프로젝트 폴더**

```bash
nano .env
```

`Ctrl+O` → `Enter`로 저장하고 `Ctrl+X`로 닫습니다. 파일 전체를 새 예시로 교체하지 말고 필요한 항목만 수정하세요. 자세한 값은 [설정 표](#configuration)에 있습니다.

**실행 위치: 라파 SSH 터미널 — 모델 없는 초기 설정 검사**

```bash
python serve.py --check --allow-mock
```

검사 조건은 `SECRET_KEY` 무작위 32자 이상, 관리자별 비밀번호 12자 이상·예제 값 금지, 서로 다른 관리자 아이디, CSRF 활성화입니다. `--allow-mock`도 계정·보안 검사를 생략하지 않습니다. `--check`는 DB를 열거나 실제 카메라·모델을 실행하지 않는 **설정 검사**입니다.

`DEFAULT_EQUIPMENT`와 `DEFAULT_QUANTITY`는 빈 DB를 처음 만드는 초기값입니다. 기존 DB의 기자재는 `.env` 수정으로 갱신되지 않으며 **관리자 화면**에서 변경합니다. 서버 시작 시 필요한 DB 테이블·이관을 처리하므로 업데이트 전에는 백업하세요.

<a id="web"></a>
## 4. 웹 확인과 수동 실행

아래 두 방식 중 현재 상태에 맞는 **하나만** 실행합니다. 수동 서버와 systemd 서버를 동시에 켜지 마세요.

**실행 위치: 라파 SSH 터미널 — `.env`가 `DETECTOR_MODE=mock`일 때**

```bash
python serve.py --allow-mock
```

웹 현황, 학생 가입·승인, 기자재 관리 화면을 확인할 수 있습니다. 이 상태에서는 인식 버튼이 비활성화되며 실제 대여·반납을 확정할 수 없습니다. 자동 테스트의 모의 거래와 운영 웹사이트의 동작은 다릅니다.

**실행 위치: 라파 SSH 터미널 — 모델 적용·검사를 마친 `yolo` 모드**

```bash
python serve.py
```

`Serving on http://0.0.0.0:8080`이 나오면 PC 브라우저에서 **`http://10.177.156.96:8080`**을 엽니다. `0.0.0.0`은 수신 설정이며 접속 주소가 아닙니다. 기본 구성은 HTTP이므로 `https://`로 입력하지 않습니다.

수동 실행 중에는 해당 터미널을 열어 둡니다. 종료는 **Ctrl+C**입니다. `python -m waitress ... wsgi:app` 대신 `serve.py`를 사용해야 배포 검사와 종료 처리를 같은 경로로 거칩니다. SSH를 닫아도 계속 운영하려면 [systemd 설치](#service)를 사용하세요.

| 화면 | PC 브라우저 주소 | 접근 권한 |
|---|---|---|
| 기자재 현황 | `http://10.177.156.96:8080/` | 로그인 없이 조회 |
| 학생 가입 / 로그인 | `/register` / `/login` | 학생 |
| 본인 대여 내역 / 비밀번호 | `/my-loans` / `/account/password` | 로그인한 학생 |
| 대여·반납 | `/scan` | 승인된 학생·관리자 |
| 관리자 로그인 / 관리 화면 | `/admin/login` / `/admin` | 선생님·개발자 |
| 학생 가입 승인 | `/admin/students` | 선생님·개발자 |
| 시스템 점검 | `/developer` | 개발자 |
| 웹·DB 상태 | `/healthz` | 상태 조회 |

`/`로 시작하는 항목은 같은 `http://라파IP:8080` 뒤에 붙이는 경로입니다. `/healthz`의 성공은 웹·DB 응답을 의미하며 카메라 정상·모델 정확도까지 보장하지 않습니다.

<a id="capture"></a>
<a id="15부-사진-촬영부터-pc-복사라벨링까지"></a>
## 5. 화면 없는 촬영과 PC 사진 전송

라파의 프로젝트·카메라·가상환경 준비를 마쳤다면 이 순서로 진행합니다. **촬영은 라파, 가져오기·회전은 PC**에서 실행합니다. 실시간 화면 없이 엔터로 촬영하며 모델은 필요하지 않습니다.

### 5-1. 라파에 접속하고 촬영 준비하기

> **실행 위치: Windows PC PowerShell — 첫 번째 창**

```powershell
ssh pi30304@10.177.156.96
```

처음 연결하는 주소면 SSH가 표시하는 장치 정보를 확인하고 연결합니다. 비밀번호는 입력해도 화면에 나타나지 않습니다. 접속 후 다음 명령부터는 라파에서 실행됩니다. 브라우저·8081 터널은 필요하지 않습니다.

> **실행 위치: 접속된 라파 SSH 터미널**

```bash
cd /home/pi30304/raspberry-pi-equipment-manager
sudo systemctl stop equipment-manager.service
git pull --ff-only origin main
source .venv/bin/activate
```

대여 서버가 카메라를 잡고 있지 않도록 먼저 멈춥니다. 다른 터미널에서 `python serve.py`로 켜 둔 서버가 있으면 그 창에서도 Ctrl+C로 종료하세요. 촬영하는 동안 사이트도 멈춥니다. `git pull`이 로컬 변경 때문에 실패하면 강제로 덮어쓰지 말고 변경 내용을 확인하세요.

### 5-2. 화면 없이 사진 찍기

> **실행 위치: 라파 SSH 터미널 — 먼저 시험 사진 한 장**

```bash
python scripts/capture_samples.py camera_check --count 1
```

3초 뒤 한 장을 촬영하고 종료합니다. 아래 5-4의 PC 가져오기로 초점·밝기를 확인하세요. 시험 사진은 학습에 포함하지 않습니다.

> **실행 위치: 라파 SSH 터미널 — 라즈베리파이 기자재 본 촬영**

```bash
python scripts/capture_samples.py raspberry_pi --manual --count 200
```

- 물체를 놓고 **엔터**를 누르면 기본 1초 뒤 한 장을 저장합니다. 손을 치울 시간이 더 필요하면 명령 끝에 `--delay 3`을 붙이세요.
- 각도·거리·배경·조명을 조금씩 바꿔가며 반복합니다.
- `--count 200`은 최대 장수입니다. **`q` 입력 후 엔터** 또는 **Ctrl+C**로 일찍 끝낼 수 있고 저장한 사진은 남습니다.
- 다음 종류를 찍기 전에 현재 촬영을 종료하세요.

> **실행 위치: 라파 SSH 터미널 — 아두이노를 찍을 때**

```bash
python scripts/capture_samples.py arduino --manual --count 200
```

> **실행 위치: 라파 SSH 터미널 — 브레드보드를 찍을 때**

```bash
python scripts/capture_samples.py breadboard --manual --count 200
```

Pi 카메라는 기존 `.env` 설정을 사용합니다. USB 카메라 0번이면 명령 끝에 `--backend opencv --camera-index 0`을 붙입니다. 사진은 **라파**의 아래 위치에 저장됩니다. 실행마다 촬영 회차 폴더가 새로 생깁니다.

```text
/home/pi30304/raspberry-pi-equipment-manager/datasets/raw/
├─ camera_check/촬영회차/시험사진.jpg
├─ raspberry_pi/촬영회차/사진.jpg
└─ arduino/촬영회차/사진.jpg
```

<a id="pc-transfer-setup"></a>
### 5-3. 가져오기 코드를 실행할 PC 준비하기

촬영을 끝낸 뒤 **Windows PC에서 새 PowerShell 창**을 여세요. SSH 창은 그대로 둬도 됩니다. 가져오기 도구가 PC에서 별도의 SSH/SFTP 연결을 만듭니다.

**파일 탐색기에서 PC의 프로젝트 폴더를 열고, 주소창에 `powershell`을 입력한 뒤 엔터**를 누르면 그 폴더에서 시작할 수 있습니다. `README.md`, `scripts`, `requirements-photo-transfer.txt`가 있는 폴더여야 합니다. Python 파일을 더블클릭하거나 라파 SSH 창에서 실행하지 마세요.

> **실행 위치: Windows PC PowerShell — 프로젝트 폴더**

```powershell
Get-Location
git pull --ff-only origin main
python --version
python -m pip install -r requirements-photo-transfer.txt
```

패키지 설치는 처음 한 번, 또는 요구사항 파일이 바뀌었을 때 실행합니다. 현재 작업하던 PC에는 설치되어 있습니다. `python`이 안 되고 `py --version`은 되면 아래 PC 명령의 `python`을 `py`로 바꾸세요. 둘 다 없으면 PC에 Python 3.10 이상을 먼저 설치해야 합니다. **라파에는 전송용 패키지를 설치하지 않습니다.**

다른 PC에 프로젝트가 아예 없을 때만 아래 명령으로 내려받고 위 설치를 진행합니다. 이미 프로젝트가 있는 PC에서는 다시 복제하지 않습니다.

> **실행 위치: Windows PC PowerShell — 새 PC 최초 준비, Git 설치 필요**

```powershell
git clone https://github.com/hapbii/raspberry-pi-equipment-manager.git
cd raspberry-pi-equipment-manager
```

### 5-4. PC로 사진 가져오기와 180도 회전

> **실행 위치: Windows PC PowerShell — 프로젝트 폴더**

```powershell
python scripts/download_photos.py --host 10.177.156.96
```

SSH 비밀번호를 입력하고 엔터를 누르면 다음 순서로 진행됩니다. 비밀번호를 코드·파일에 저장하지 않습니다.

1. 라파 `datasets/raw/` 아래의 기자재별·촬영 회차별 폴더를 찾습니다.
2. JPG/JPEG/PNG 사진을 PC의 임시 파일로 한 장씩 받습니다.
3. PC에서 **180도 회전**해 같은 폴더 구조로 저장합니다. 라파 원본은 수정·삭제하지 않습니다.
4. `training/classes.txt`도 복사하고 완료 장수와 PC 저장 위치를 표시합니다.

기본 저장 위치는 **워크스페이스가 아니라 PC 다운로드 폴더**입니다. 현재 PC는 아래 경로이며, 다른 PC에서는 `happy`가 해당 Windows 사용자 이름으로 바뀝니다.

```text
C:\Users\happy\Downloads\equipment-photos-날짜시간-식별자\
├─ classes.txt
├─ transfer.json
└─ raw\
   ├─ camera_check\촬영회차\시험사진.jpg
   ├─ raspberry_pi\촬영회차\사진.jpg
   └─ arduino\촬영회차\사진.jpg
```

워크스페이스 안에 저장하려면 기본 명령 **대신** 아래처럼 실행합니다.

> **실행 위치: Windows PC PowerShell — 프로젝트 폴더 안으로 저장하는 방법**

```powershell
$captureFolder = Join-Path (Get-Location).Path ("datasets\labeling-photos-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
python scripts/download_photos.py --host 10.177.156.96 --output "$captureFolder"
```

성공 메시지에 나온 폴더를 파일 탐색기로 엽니다. `datasets`는 GitHub 업로드에서 제외됩니다. 매번 새 폴더가 생기며 이미 있는 폴더를 지정하면 덮어쓰지 않고 중단합니다. 증분 복사가 아니라 **매번 새 복사본**을 만드는 방식입니다.

> **실행 위치: Windows PC PowerShell — 한 종류만 가져오는 선택 예시**

```powershell
python scripts/download_photos.py --host 10.177.156.96 --class-name raspberry_pi
```

전송 중 Ctrl+C나 통신 오류가 발생하면 완성된 사진은 남고 임시 파일은 정리합니다. `transfer.json`의 `status`가 `complete`이면 전체 완료, `incomplete`이면 일부 완료입니다. 재실행은 새 폴더로 처음부터 복사합니다. JPG는 품질 95로 재압축됩니다. 카메라 방향을 고쳐 회전할 필요가 없으면 `--rotation 0`을 붙입니다.

**이 단계에서 만든 PC 사진으로 라벨링하세요.** 나중에 라파의 거꾸로 된 사진으로 교체하거나 사진만 다시 회전하면 박스 좌표가 맞지 않습니다. 기존 TXT/JSON 라벨은 가져오기 대상이 아닙니다.

<a id="labeling"></a>
## 6. X-AnyLabeling 라벨링과 Colab 학습

사진을 PC로 가져와 방향을 확인한 뒤 시작합니다. 촬영 폴더 이름이 라벨을 대신하지 않으며, 각 물체의 위치와 종류를 직접 표시해야 합니다.

### 6-1. X-AnyLabeling에서 박스 그리기

> **작업 위치: Windows PC의 X-AnyLabeling 프로그램 — 터미널 명령 아님**

현재 PC는 바탕화면의 **X-AnyLabeling 4.0.6**으로 실행합니다. 다른 PC에는 [공식 Windows 배포판](https://github.com/CVHub520/X-AnyLabeling/releases/tag/v4.0.6)을 준비하세요. 아래 메뉴·단축키는 기본 설정 기준이며 한국어 설정에서는 메뉴가 번역되어 보일 수 있습니다.

1. **Open Dir / Ctrl+U**로 `raw/raspberry_pi/촬영회차`처럼 실제 사진이 있는 폴더를 엽니다. 시험용 `camera_check`는 제외합니다.
2. 사진 방향을 확인하고 **R**로 일반 사각형을 선택합니다. 물체를 감싸는 대각선의 두 모서리를 차례로 클릭합니다.
3. 이름 입력창에 해당 기자재의 영문 클래스명을 입력합니다. 한 사진에 대상이 여러 개면 각각 박스를 그립니다.
4. 저장 상태를 확인하고 **D**로 다음 사진, **A**로 이전 사진으로 이동합니다. 기본 자동 저장은 `File > Auto Save`에서 확인합니다.

처음에는 촬영 회차 하나씩 작업하면 사진과 내보낸 라벨을 대응시키기 쉽습니다. 물체 전체를 포함하되 불필요한 배경을 크게 넣지 마세요. 학습 대상이 아닌 손·책상에 기자재 이름을 붙이지 않습니다.

번호는 **복사된 `classes.txt`의 줄 순서**입니다. 현재 저장소 기본값은 다음과 같습니다.

| YOLO 번호 | 입력할 이름 | 기자재 |
|---|---|---|
| 0 | `raspberry_pi` | 라즈베리파이 |
| 1 | `arduino` | 아두이노 |
| 2 | `breadboard` | 브레드보드 |
| 3 | `wheel` | 바퀴 |
| 4 | `ultrasonic_sensor` | 초음파 센서 |
| 5 | `servo_motor` | 서보 모터 |
| 6 | `pir_sensor` | PIR 센서 |

모든 회차에서 같은 목록을 사용하세요. 아두이노만 있는 폴더에서도 아두이노는 **1번**입니다. 목록을 바꾸려면 라벨링 시작 전에 `classes.txt`와 학습용 `data.yaml`의 `names`를 함께 맞추세요.

<a id="labeling-export"></a>
### 6-2. YOLO 학습용 TXT 내보내기

> **작업 위치: Windows PC의 X-AnyLabeling 프로그램**

**일반 저장으로 생기는 JSON은 편집용입니다. 학습용 TXT는 별도로 내보내야 합니다.**

1. `Export Annotations > Export YOLO Annotations`를 선택합니다.
2. 작업 종류는 **객체 탐지(Detection)**를 선택합니다. Segmentation·Pose·회전 박스 작업이 아닙니다.
3. 클래스 설정 파일을 요청하면 사진과 함께 받은 **`classes.txt`**를 선택합니다.
4. 내보낸 결과를 확인합니다. 기본 경로는 연 사진 폴더 아래 `labels`이며 따로 지정했다면 그 폴더를 확인합니다.

```text
촬영회차/
├─ raspberry_pi_001.jpg        ← 회전된 PC 사진
├─ raspberry_pi_001.json       ← 편집용 작업 파일
└─ labels/
   └─ raspberry_pi_001.txt     ← YOLO 학습용
```

TXT 한 줄은 `클래스번호 중심X 중심Y 너비 높이`입니다. 좌표와 크기는 0~1 범위이며 프로그램이 계산합니다. 사진과 TXT의 **확장자를 제외한 이름이 일치**하는지 확인하고, 박스를 수정한 뒤에는 TXT도 다시 내보내세요. JSON도 보관하면 나중에 다시 편집할 수 있습니다. 메뉴·단축키·저장 방식은 [X-AnyLabeling 4.0.6 공식 설명서](https://github.com/CVHub520/X-AnyLabeling/blob/v4.0.6/docs/en/user_guide.md)를 기준으로 정리했습니다.

### 6-3. 라벨링 다음 단계: Colab 학습 준비

> **작업 위치: Windows PC 파일 탐색기, 이후 Google Drive·Colab 브라우저**

회전된 사진과 TXT를 짝지어 모읍니다. 같은 회차를 train·val·test에 흩뿌리지 말고 **촬영 회차 단위로 분리**하세요. 같은 사진을 다시 다운로드한 복사본도 서로 다른 묶음에 넣지 않습니다. `camera_check`는 제외합니다.

```text
equipment_dataset/
├─ data.yaml
├─ images/
│  ├─ train/사진A.jpg
│  ├─ val/사진B.jpg
│  └─ test/사진C.jpg
└─ labels/
   ├─ train/사진A.txt
   ├─ val/사진B.txt
   └─ test/사진C.txt
```

1. `training/dataset_example.yaml`을 위 폴더의 `data.yaml`로 복사합니다. `names` 번호는 라벨링에 쓴 `classes.txt`와 같아야 합니다.
2. `equipment_dataset`을 Google Drive의 **내 드라이브 바로 아래**에 올립니다. 예시 YAML의 `path`는 `/content/drive/MyDrive/equipment_dataset`입니다.
3. [학습 노트북](training/YOLO_기자재_학습_Colab.ipynb)을 내려받아 Colab에서 열고 GPU 런타임을 선택합니다.
4. 셀을 위에서 아래로 실행하고, Drive 연결 뒤 `DATA_YAML`이 실제 `data.yaml` 위치와 일치하는지 확인합니다. 기본 노트북은 `yolo11n.pt`, 80 epochs, 입력 크기 416, batch 16으로 시작합니다. GPU 메모리가 부족하면 batch를 낮춥니다.
5. 사진 추론 셀의 `TEST_IMAGES`는 기본 `equipment_dataset/field_test_images`입니다. 이 별도 폴더가 없다면 `/content/drive/MyDrive/equipment_dataset/images/test`로 바꿔 준비한 시험 사진을 사용합니다. 학습에 사용하지 않은 사진으로 확인하세요.
6. 마지막 다운로드 셀에서 `best.pt`와 `best_ncnn_model.zip`을 PC에 보관합니다. `/content/runs` 결과는 Colab 세션이 끝나면 사라질 수 있으므로 다운로드·Drive 보관을 확인하세요. NCNN ZIP은 라파로 보내기 전에 폴더로 풉니다.
7. [모델 적용·실제 장치 검사](#model)로 진행합니다. 자세한 데이터 구조는 [학습 안내](training/README.md)를 참고하세요.

가져오기 도구는 **학습용 PC 사진만 회전**합니다. 실제 인식용 카메라 입력은 아직 기존 방향이므로 모델 적용 시 입력 방향도 맞추거나 뒤집힌 방향을 포함해 학습·검증해야 합니다.

<a id="model"></a>
## 7. 학습 모델을 라파에 적용하기

### 7-1. 파일 복사

촬영 프로그램·진단 도구·서버를 먼저 종료합니다. systemd 서버라면 [서비스 중지](#service)를 사용하고, 수동 실행은 그 터미널에서 Ctrl+C를 누릅니다.

**실행 위치: 라파 SSH 터미널 — 저장 폴더 준비**

```bash
cd ~/raspberry-pi-equipment-manager
mkdir -p models
```

**실행 위치: PC PowerShell — `best.pt`가 다운로드 폴더에 있을 때**

```powershell
scp "$env:USERPROFILE\Downloads\best.pt" pi30304@10.177.156.96:~/raspberry-pi-equipment-manager/models/
```

NCNN을 사용하려면 ZIP을 먼저 `best_ncnn_model` 폴더로 풀고, 파일 하나가 아닌 **폴더 전체**를 가져갑니다. Colab 노트북은 NCNN을 입력 크기 320으로 내보냅니다.

**실행 위치: PC PowerShell — NCNN을 선택할 때 위 명령 대신**

```powershell
scp -r "$env:USERPROFILE\Downloads\best_ncnn_model" pi30304@10.177.156.96:~/raspberry-pi-equipment-manager/models/
```

**실행 위치: 라파 SSH 터미널 — 복사 결과 확인**

```bash
ls -lah models
```

기존 모델을 교체한다면 이전 모델도 별도 이름으로 보관하세요. NCNN을 다른 이름으로 내보냈다면 폴더 이름과 `.env` 경로를 일치시킵니다. 속도 개선 정도는 실제 장치에서 비교하며, 변환만으로 정확도나 속도를 보장하지 않습니다. [NCNN 공식 안내](https://docs.ultralytics.com/integrations/ncnn/)

### 7-2. 인식·카메라 설정

**편집 위치: 라파 프로젝트의 `.env` — `best.pt` + Pi 카메라 예시**

```dotenv
DETECTOR_MODE=yolo
YOLO_MODEL_PATH=models/best.pt
YOLO_IMAGE_SIZE=320
YOLO_CONFIDENCE=0.60
YOLO_FRAME_COUNT=5
YOLO_MIN_VOTES=3
YOLO_MAX_DETECTIONS=5
INFERENCE_THREADS=2
GC_INTERVAL_SCANS=20
CAMERA_BACKEND=picamera2
CAMERA_WIDTH=640
CAMERA_HEIGHT=480
CAMERA_BUFFER_COUNT=2
CAMERA_WARMUP_SECONDS=0.5
GPIO_ENABLED=false
```

NCNN이면 `YOLO_MODEL_PATH=models/best_ncnn_model`로 바꿉니다. 내보낼 때 사용한 입력 크기와 `YOLO_IMAGE_SIZE`를 맞추세요. USB 카메라면 아래 두 값으로 카메라 부분을 변경합니다.

**편집 위치: 라파 `.env` — USB 카메라를 쓰는 경우만**

```dotenv
CAMERA_BACKEND=opencv
CAMERA_INDEX=0
```

### 7-3. 모델 이름과 관리자 기자재 이름 연결

모델 이름은 `raspberry_pi`이고 관리자 화면은 `라즈베리파이`처럼 한글 이름일 수 있습니다. 이때 별칭을 지정합니다.

**편집 위치: 라파 `.env` — 현재 7종 클래스 기준 예시**

```dotenv
YOLO_CLASS_ALIASES='{"raspberry_pi":"라즈베리파이","arduino":"아두이노","breadboard":"브레드보드","wheel":"바퀴","ultrasonic_sensor":"초음파 센서","servo_motor":"서보 모터","pir_sensor":"PIR 센서"}'
```

왼쪽은 학습 클래스, 오른쪽은 **관리자 화면에 등록된 정확한 기자재 이름**입니다. 띄어쓰기까지 일치시킵니다. 별칭 설정이 기자재를 자동으로 추가해 주지는 않습니다. 기본 DB에는 멀티미터·아두이노·브레드보드가 들어가므로 실제 학습 대상과 다른 기자재는 관리 화면에서 추가·정리하고 실제 수량을 입력하세요. `.env`의 초기 목록을 바꾸는 것만으로 기존 DB가 갱신되지 않습니다.

**카메라 방향:** 사진 가져오기는 PC 복사본만 회전합니다. 현재 실제 인식 코드에는 같은 180도 회전을 자동 적용하는 설정이 없습니다. 거꾸로 설치한 카메라를 유지한다면 실제 입력 방향 보정 또는 두 방향을 포함한 학습·검증이 추가로 필요합니다. 라벨링 사진만 바로 세웠다고 실제 인식도 자동으로 바로 서는 것은 아닙니다.

<a id="diagnostics"></a>
## 8. 실제 카메라·모델·메모리 검사

카메라를 쓰는 다른 프로그램과 서버를 중지하고, 라파 프로젝트 폴더에서 가상환경을 활성화합니다. 카메라 앞에 학습한 기자재 하나를 놓으세요.

**실행 위치: 라파 SSH 터미널 — 순서대로 실행**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
python serve.py --check
python scripts/pi_diagnostics.py
python scripts/memory_soak_test.py --scans 50 --interval 0.3 --max-growth-mb 120
```

| 검사 | 확인하는 것 | 확인하지 않는 것 |
|---|---|---|
| `serve.py --check` | 계정·배포 설정, 모델 경로 접근 | DB·실제 카메라·모델 추론 |
| `pi_diagnostics.py` | 실제 모델 로딩·카메라 프레임·추론 | 모든 기자재의 인식 정확도 |
| `memory_soak_test.py` | 반복 인식 성공 수, 실행 중 RSS 증가 추이 | 모든 환경의 메모리 누수 부재 |

진단에 `카메라와 모델 실행은 정상`이라고 나와도 물체가 검출되지 않을 수 있습니다. 그 경우 사진·클래스·조명·거리·신뢰도를 점검합니다. 메모리 검사는 인식 성공이 0회이거나 RSS를 읽지 못하면 실패합니다. 종료 후 메모리만 줄어든 것으로 통과 처리하지 않습니다.

**실행 위치: 라파 SSH 터미널 — 짧은 검사를 통과한 뒤 배포 전 반복 검사**

```bash
python scripts/memory_soak_test.py --scans 200 --interval 0.3 --max-growth-mb 120
```

실제 운영 시간에 맞춘 추가 장시간 시험도 필요합니다. 결과는 사용한 모델·해상도·카메라 설정과 함께 보관하세요. 이 진단들은 앱과 DB를 초기화할 수 있지만 대여·반납 거래를 생성하는 도구는 아닙니다.

사진 한 장에서 모델의 클래스 출력을 확인하려면 아래 도구도 사용할 수 있습니다. 예시 파일을 실제 시험 사진 경로로 바꾸세요.

**실행 위치: 라파 SSH 터미널 — 모델과 시험 사진이 준비된 경우**

```bash
python scripts/test_model_image.py models/best.pt datasets/example.jpg --imgsz 320 --conf 0.60
```

결과 이미지는 `runs/single-image-test/`에 저장합니다. 시험 사진 이름만 적은 예시이므로 `datasets/example.jpg`를 먼저 준비해야 합니다. 점검 후에는 [수동 실행](#web) 또는 [서비스 실행](#service) 중 하나로 서버를 켭니다.

<a id="service"></a>
## 9. 부팅 자동 실행·업데이트·종료

### 9-1. systemd 서비스 설치

서비스 설치는 **라파의 일반 사용자로 SSH 로그인한 후** `sudo`를 붙여 실행합니다. 프로젝트 `.venv`와 `.env`가 준비되어 있어야 합니다. 별도의 수동 서버가 있으면 먼저 Ctrl+C로 종료하세요.

종료·업데이트 버튼을 사용할 경우 polkit 패키지를 준비합니다.

**실행 위치: 라파 SSH 터미널 — 종료 기능 사용 시**

```bash
sudo apt install -y polkitd
```

아래에서 현재 상태에 맞는 **한 가지 설치 명령만** 사용합니다.

**실행 위치: 라파 SSH 터미널 — 모델 없이 웹 확인용 설치**

```bash
cd ~/raspberry-pi-equipment-manager
sudo bash deploy/install_service.sh --allow-mock --enable-poweroff --enable-update
```

**실행 위치: 라파 SSH 터미널 — 실제 `yolo` 운영용 설치**

```bash
cd ~/raspberry-pi-equipment-manager
sudo bash deploy/install_service.sh --enable-poweroff --enable-update
```

설치기는 설정을 검사하고 실행 사용자·경로에 맞는 서비스 파일을 만들며, 현재 서비스를 재시작하고 다음 부팅의 자동 실행을 등록합니다. `.env`와 운영 DB를 재생성하지 않습니다. 웹·DB의 `/healthz` 응답도 확인하지만, 실제 카메라 검사는 [8절](#diagnostics)에서 별도로 합니다.

| 옵션 | 의미 |
|---|---|
| `--allow-mock` | 현재 `mock` 설정으로 웹 확인용 설치 허용 |
| `--enable-poweroff` | 개발자 화면의 라파 종료·프로그램만 종료 권한 설치 |
| `--enable-update` | 개발자 화면의 Git 업데이트·프로그램 재시작 권한 설치 |
| `--check` | 위 옵션에 추가하면 검사만 하고 서비스 설치·실행은 하지 않음 |

종료 기능이 필요 없으면 `--enable-poweroff`, 업데이트 기능이 필요 없으면 `--enable-update`를 빼세요. 기존 설치를 해당 옵션 없이 재설치하면 그 기능의 권한이 해제됩니다. **부팅할 때 `git pull`은 자동 실행하지 않습니다.** 모델 준비 후 `mock`에서 `yolo`로 전환할 때는 `.env` 수정·검사 후 실제 운영용 설치 명령으로 재설치해 실행 옵션도 맞춥니다.

### 9-2. 상태 확인과 제어 명령

**실행 위치: 라파 SSH 터미널 — 상태 확인**

```bash
systemctl is-active equipment-manager.service
systemctl is-enabled equipment-manager.service
sudo systemctl status equipment-manager.service --no-pager -l
curl --noproxy '*' --fail http://127.0.0.1:8080/healthz
```

`active`는 지금 실행 중, `enabled`는 다음 부팅 자동 시작 등록입니다. 아래 표의 명령은 **필요한 행 하나씩** 라파 SSH 터미널에서 실행합니다.

| 할 일 | 라파에서 실행할 명령 | 영향 |
|---|---|---|
| 잠시 멈추기 | `sudo systemctl stop equipment-manager.service` | 웹 서버 중지, SSH 유지 |
| 다시 켜기 | `sudo systemctl start equipment-manager.service` | 중지한 웹 서버 시작 |
| 설정·코드 반영 | `sudo systemctl restart equipment-manager.service` | 서버 종료 후 다시 시작 |
| 부팅 자동 시작만 해제 | `sudo systemctl disable equipment-manager.service` | 현재 실행은 유지, 다음 부팅 시작 안 함 |
| 현재 실행·자동 시작 모두 해제 | `sudo systemctl disable --now equipment-manager.service` | 서버 중지 및 자동 시작 해제 |
| 최근 로그 보기 | `journalctl -u equipment-manager.service -n 80 --no-pager` | 상태·오류 확인 |
| 실시간 로그 보기 | `journalctl -u equipment-manager.service -f` | Ctrl+C는 로그 보기만 종료 |

기본 서비스는 비정상 종료 시 재시작하며, 사용자가 `stop`으로 중지하면 그 상태를 유지합니다. 부팅 자동 시작 등록 자체는 남으므로 라파를 재부팅하면 다시 시작할 수 있습니다.

### 9-3. 웹에서 프로그램만 종료하거나 라파 끄기

**작업 위치: PC 브라우저 → 개발자 로그인 → 시스템 화면**

종료 영향 확인과 개발자 비밀번호 재입력 후 약 10초 지연된 종료를 요청합니다.

| 기능 | 결과 | 다시 사용하려면 |
|---|---|---|
| 프로그램만 종료 | 웹 서버 중지, 라파 전원·SSH 유지 | SSH에서 서비스 `start` |
| 라즈베리파이 종료 | OS 종료, 웹·SSH 연결 종료 | 정상 종료 후 필요할 때 전원 재연결 |

프로그램만 종료 기능은 systemd로 실행한 서버를 대상으로 합니다. 수동 서버는 Ctrl+C로 종료합니다. 버튼 설치 중에는 종료를 실행하지 않습니다. `.env`만 바꾸거나 `git pull`만 하는 것으로 OS 종료 권한이 생기지는 않습니다.

**실행 위치: 라파 SSH 터미널 — 터미널에서 직접 안전 종료할 때만**

```bash
sudo poweroff
```

로그인·촬영·파일 전송을 마치고 종료합니다. OS 종료를 확인한 뒤 전원을 분리하세요.

<a id="web-update"></a>
### 9-4. 웹 버튼으로 코드 업데이트와 자동 재시작

**최초 한 번은 SSH 설치가 필요합니다.** 기존 서비스에는 업데이트 작업과 권한이 없으므로 `git pull`만으로는 버튼이 활성화되지 않습니다. 모든 사용자가 이용을 마친 뒤 설치하세요. 별도 수동 서버는 먼저 Ctrl+C로 종료합니다.

**실행 위치: 라파 SSH 터미널 — 기존 프로젝트 업데이트 및 설치 준비**

```bash
cd ~/raspberry-pi-equipment-manager
git status --short
git pull --ff-only origin main
sudo apt install -y polkitd git
```

Git 명령에 오류가 없으면 [9-1](#service)의 현재 모드에 맞는 설치 명령 **한 가지**를 실행합니다. 모델 없는 `mock`이면 `--allow-mock --enable-poweroff --enable-update`, 실제 `yolo`면 `--enable-poweroff --enable-update`를 지정합니다. 설치기는 현재 프로젝트의 절대 경로와 SSH 사용자를 기억하고 서버를 재시작합니다. 다른 경로로 이동했다면 설치기를 다시 실행하세요.

**이후 사용 위치: 브라우저 → 개발자 로그인 → 시스템 → 프로그램 업데이트…**

1. 모든 사용자의 대여·반납·인식이 끝났는지 확인합니다.
2. 개발자 비밀번호와 안내 확인 후 **확인 · 업데이트 시작**을 누릅니다.
3. 약 3초 후 별도 systemd 작업이 웹서버를 중지하고 **2초** 기다립니다.
4. 현재 DB를 `backups/`에 백업한 뒤, 설치된 프로젝트 경로에서 해당 일반 사용자 권한으로 `git pull --ff-only origin main`을 실행합니다.
5. 새 코드의 `serve.py --check`를 통과하면 **2초** 기다린 뒤 서버를 다시 켜고 `/healthz` 응답을 확인합니다. `mock` 설치는 검사에도 `--allow-mock`을 사용합니다.
6. 잠시 후 시스템 화면으로 돌아가 **최근 업데이트 결과**와 버전을 확인합니다. 요청 접수 화면만으로 업데이트 성공을 판단하지 마세요.

웹 프로그램이 종료되어도 업데이트 작업은 계속되고, 브라우저를 닫아도 중단되지 않습니다. 라파 전원과 SSH 연결은 유지됩니다. 처리 중에는 종료 버튼을 추가로 누르거나 수동 Git 작업을 하지 마세요. 인터넷 연결이 필요하며 네트워크·시작 시간에 따라 수십 초 이상 걸릴 수 있습니다.

- `main` 브랜치와 깨끗한 작업 폴더가 필요합니다. 수정된 파일·미추적 파일이 있으면 시작 전에 중단합니다. Git에서 제외한 `.env`, DB, 모델, 사진은 그대로 둡니다.
- Git 충돌·네트워크 오류·DB 백업 실패 시 강제 덮어쓰기나 자동 병합을 하지 않습니다. 서버를 멈춘 뒤 실패했다면 재시작을 시도하고 실패 단계를 기록합니다.
- 새 코드 실행 자체에 문제가 있으면 서버가 복구되지 않을 수 있습니다. **코드·DB를 이전 버전으로 자동 롤백하지 않습니다.** 백업과 로그를 확인하고 SSH에서 해결하세요.
- 버튼은 **코드 업데이트용**입니다. Python 패키지 설치, OS 패키지 변경, 모델 전송, systemd·권한 재설치는 하지 않습니다. 요구사항이나 배포 설정이 바뀐 버전은 [SSH 업데이트](#maintenance)와 서비스 재설치를 진행하세요. 설치된 업데이트 실행기 자체도 서비스 재설치로 반영합니다.
- DB 백업은 업데이트마다 생기며 자동 삭제하지 않습니다. 저장 공간과 별도 PC 보관을 관리하세요.

**실행 위치: 라파 SSH 터미널 — 오류 또는 장시간 미복구 시 확인**

```bash
sudo systemctl status equipment-manager-update.service --no-pager -l
sudo journalctl -u equipment-manager-update.service -n 80 --no-pager
sudo systemctl status equipment-manager.service --no-pager -l
sudo journalctl -u equipment-manager.service -n 80 --no-pager
```

업데이트 작업이 끝난 상태에서 원인을 해결했으면 `sudo systemctl start equipment-manager.service`로 다시 시작합니다. 업데이트 서비스는 일회성 작업이므로 성공 후 `inactive`여도 정상입니다. 상태 파일은 `/var/lib/equipment-manager-update/status.json`에 기록합니다. 강제 종료·전원 차단으로 완료 기록이 없으면 로그를 확인하세요.

작업은 root 소유로 설치된 실행기가 관리하고, Git·DB 백업·설정 검사는 일반 사용자로 실행합니다. 웹 앱에는 고정된 업데이트 타이머 시작 권한만 부여합니다. 실행기 오류·시간 초과 때도 재시작을 시도하도록 systemd의 `ExecStopPost`를 사용합니다. [systemd 공식 서비스 설명](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml)

<a id="usage"></a>
## 10. 학생·선생님·개발자 사용법

사이트에 처음 접속하면 **사용 유의사항 팝업**이 표시됩니다. 물품을 1개씩 놓기, 라파 카메라 사용, 인식 결과 확인 후 확정, 본인 계정·반납 기한·로그아웃을 안내합니다. 닫은 뒤에는 같은 탭의 새로고침·페이지 이동에서 다시 표시하지 않으며, 하단 **사용 유의사항** 버튼으로 언제든 다시 열 수 있습니다. 브라우저가 세션 저장을 차단하면 페이지를 옮길 때 다시 표시될 수 있습니다.

홈 화면에서 대여·반납과 관리자로 이동할 때는 **상단 메뉴**를 사용하세요.

### 10-1. 권한과 가입 승인

| 기능 | 비로그인 | 승인된 학생 | 선생님 | 개발자 |
|---|---|---|---|---|
| 기자재 현황 조회 | 가능 | 가능 | 가능 | 가능 |
| 대여·반납 | 불가 | 본인 학번 | 학번 지정 | 학번 지정 |
| 학생 본인 내역·비밀번호 | 불가 | 가능 | 학생 관리 화면 사용 | 학생 관리 화면 사용 |
| 가입 승인·중지·비밀번호 재설정 | 불가 | 불가 | 가능 | 가능 |
| 기자재·거래 관리, CSV | 불가 | 불가 | 가능 | 가능 |
| 취소된 거래 영구 삭제 | 불가 | 불가 | 불가 | 가능 |
| 시스템·오류 로그·종료 | 불가 | 불가 | 불가 | 가능 |

1. 학생이 `/register`에서 숫자 2~20자리 학번, 이름, 12~128자 비밀번호로 가입합니다.
2. 선생님·개발자가 `/admin/students`에서 본인을 확인하고 승인합니다. 가입만으로는 로그인할 수 없습니다.
3. 학생이 `/login`에서 로그인하면 본인 학번으로 대여·반납하고 `/my-loans`에서 본인 내역을 확인합니다.
4. 비밀번호 분실 시 관리자가 본인 확인 후 새 비밀번호를 설정해 전달합니다. 기존 비밀번호를 보여 주는 기능은 없습니다.

학생 계정은 같은 학번의 기존 거래와 연결되므로 승인 전 본인 확인이 필요합니다. 학생 비밀번호는 해시로 DB에 저장하고 관리자 자격 증명은 `.env`에서 관리합니다. 계정 사용 중지·비밀번호 변경은 기존 로그인 세션을 무효화합니다. 관리자 `.env` 변경은 서버 재시작 후 반영됩니다.

기본 세션은 15분 미사용 또는 로그인 후 8시간이면 만료됩니다. 현황 자동 갱신은 로그인 시간을 연장하지 않습니다. 공용 단말은 사용 후 로그아웃하세요. PIN은 사용하지 않으며 예전 `STATION_PIN`으로 로그인을 대신할 수 없습니다.

로그인은 계정별 5분에 5회, 같은 IP에서는 5분에 60회로 제한하고 가입은 같은 IP에서 5분에 20회로 제한합니다. 여러 학생이 학교의 같은 외부 IP를 공유할 수 있으므로 제한 안내가 뜨면 표시된 시간 뒤 다시 시도하세요.

### 10-2. 대여와 반납

**작업 위치: PC·휴대전화 브라우저의 대여·반납 화면 + 라파 촬영 위치**

1. 로그인하고 `대여·반납`을 엽니다. 학생 학번은 자동으로 지정되며 바꿀 수 없습니다.
2. 대여 또는 반납을 선택합니다. 대여는 사유가 필요하고 반납은 사유가 필요 없습니다.
3. 라파 카메라 앞에 기자재 **하나만** 놓고 인식합니다.
4. 표시된 종류가 실제 물건과 같은지 확인한 뒤 최종 버튼으로 확정합니다. 잘못 인식하면 확정하지 말고 다시 촬영합니다.
5. 성공 안내와 본인 내역·현황 반영을 확인합니다.

화면은 한 번에 1개씩 처리합니다. 인식 결과는 기본 90초 후 만료되며 한 번만 사용할 수 있습니다. 같은 학생·기자재·작업의 짧은 중복 요청도 차단합니다. 처리 중 연결이 끊기면 서버 저장은 완료됐을 수 있으므로 바로 재시도하기 전에 내역부터 확인하세요.

기자재별 대여 기간은 관리자가 정합니다. **0일은 무기한이 아니라 당일 반납**입니다. 기한이 지난 미반납이 하나라도 있으면 그 학번은 새 대여가 차단되고, 반납은 계속 가능합니다. 과거 거래의 기한은 기자재 기본 기간 변경으로 소급 수정되지 않습니다. 날짜는 라파의 로컬 날짜 기준입니다.

### 10-3. 기자재 수량·거래 관리

- 기자재를 추가하고 실제 전체 수량과 대여 기간을 입력합니다. 초기 수량 10개는 예시이므로 실제 수량으로 맞추세요.
- 여러 기자재를 체크해 **선택 저장 / 선택 제거**할 수 있습니다. 한 항목이라도 잘못되면 선택 작업 전체를 반영하지 않습니다.
- 사용 가능 수량은 `전체 수량 − 실제 미반납 수량`과 일치해야 합니다. 수량을 수정해 미반납 기록을 없앨 수 없습니다.
- 미반납이 있는 종류는 제거할 수 없습니다. 제거는 목록에서 비활성화하며 기존 거래는 보존합니다.
- 잘못된 거래는 **거래 취소**로 수량·미반납 관계를 되돌립니다. 이미 반납과 연결된 대여 등은 관계에 따라 취소가 제한됩니다.
- 개발자의 **영구 삭제**는 먼저 취소된 거래만 가능합니다. 취소와 영구 삭제는 다른 작업입니다.
- 최근 거래 화면은 최대 150건, CSV는 최근 최대 500건입니다. **CSV는 전체 DB 백업이 아닙니다.** 미반납은 100개 조합씩 페이지로 나누며 요약 수량은 전체 기준입니다.

### 10-4. 개발자 시스템 화면

메모리 RSS, DB·모델 경로, 인식 상태·통계, 최근 오류 로그를 확인합니다. 화면을 여는 것만으로 카메라가 켜지지는 않습니다. `카메라·모델 실제 점검`은 카메라와 모델을 실제로 실행하므로 촬영 프로그램을 종료한 뒤 사용하세요.

`최근 인식·점검 성공`은 마지막 결과이며 현재 장치 상태를 계속 검사했다는 뜻이 아닙니다. 오류 로그 삭제는 프로젝트 로그를 지우며 systemd의 `journalctl` 로그를 지우는 기능은 아닙니다. 로그에 필요한 오류 원인을 기록한 뒤 정리하세요.

<a id="network"></a>
## 11. 학교 네트워크와 접속 점검

기본 주소는 `http://라파IP:8080`입니다. `127.0.0.1`은 **접속하는 기기 자신**이므로 PC에서 라파를 보려면 라파 IP를 사용합니다. 기본 8080 포트는 [배포 설정 코드](equipment_manager/deployment.py)에 지정되어 있고 `PORT`라는 `.env` 항목은 없습니다.

**실행 위치: 라파 SSH 터미널 — 주소·웹 응답 확인**

```bash
hostname -I
python scripts/network_info.py
curl --noproxy '*' --fail http://127.0.0.1:8080/healthz
ss -ltnp 'sport = :8080'
```

**실행 위치: PC PowerShell — 라파까지의 포트 연결 확인**

```powershell
Test-NetConnection 10.177.156.96 -Port 22
Test-NetConnection 10.177.156.96 -Port 8080
```

| 결과 | 다음 확인 |
|---|---|
| 라파 내부 `curl`부터 실패 | 서버 실행 상태·서비스 로그·포트 충돌 |
| SSH는 되는데 웹 8080 연결 실패 | 서버 수신 상태, 라파·학교 방화벽 |
| 같은 교실만 되고 다른 교실은 실패 | VLAN·Wi-Fi 기기 격리·건물 간 접근 정책 |
| SSH·웹 모두 실패 | 현재 IP, 라파 전원, 네트워크 연결 |
| 브라우저가 HTTPS 오류 표시 | 주소를 `http://...:8080`으로 입력했는지 |

같은 Wi-Fi 이름이어도 기기 간 통신이 차단될 수 있고, 핫스팟도 종류에 따라 다릅니다. 학교 전산 담당자와 라파의 DHCP 주소 예약 또는 고정 IP, 필요한 내부 접근을 확인하세요. 이 프로젝트의 기본 설치에는 인터넷 공개·HTTPS 인증서 설정이 포함되어 있지 않습니다. HTTPS를 별도로 구성했다면 그때 `SESSION_COOKIE_SECURE=true`를 적용합니다. HTTP에서 먼저 켜면 로그인 쿠키가 전달되지 않을 수 있습니다.

<a id="maintenance"></a>
## 12. 업데이트·백업·복구

### 12-1. 어디에 무엇이 저장되나요?

아래 경로는 각 기기의 프로젝트 폴더 기준입니다. PC에 받은 사진은 별도 다운로드 폴더 또는 지정한 `--output`에 있습니다.

| 위치 | 내용 | 관리 방법 |
|---|---|---|
| `.env` | 웹 계정·장치·모델 설정 | 기존 값 보존, 비공개로 별도 보관 |
| `instance/equipment.db` | 기자재·계정·대여·반납·세션 | DB 백업 도구 사용. `DATABASE`로 변경 가능 |
| `instance/errors.log` 및 회전 파일 | 앱 오류 로그 | 개발자 화면 또는 파일로 확인 |
| `backups/` | SQLite 백업 파일 | 라파 밖에도 복사. 자동 보존 기간·스케줄은 없음 |
| `models/` | `best.pt`·NCNN 모델 | 현재 모델과 직전 모델 별도 보관 |
| `datasets/raw/` | 라파 촬영 원본 | PC 복사·확인 후 보관 계획에 따라 정리 |
| PC 전송 폴더 | 회전된 사진·클래스 목록·전송 결과 | JSON/TXT 라벨과 함께 보관 |
| `runs/` | 추론·학습 결과 | 필요한 결과를 골라 보관 |

`.env`, DB·로그, 사진·데이터셋, 모델, 백업, 임시 파일은 `.gitignore`의 제외 대상입니다. **GitHub에 코드를 올려도 운영 데이터가 백업되는 것은 아닙니다.**

### 12-2. DB 백업과 PC 보관

**실행 위치: 라파 SSH 터미널 — 프로젝트 폴더·가상환경**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/backup_db.py
ls -lt backups
```

`.env`의 `DATABASE`를 읽고, 기본값은 `instance/equipment.db`입니다. `backups/equipment-날짜-시간.db`를 만들고 `quick_check`를 통과한 뒤 완료 메시지를 출력합니다. SQLite 백업 API를 사용하므로 서버 실행 중에도 일관된 DB 사본을 만들 수 있습니다. [SQLite 백업 문서](https://www.sqlite.org/backup.html)

**실행 위치: PC PowerShell — 출력된 실제 백업 파일명으로 바꿔 실행**

```powershell
scp pi30304@10.177.156.96:~/raspberry-pi-equipment-manager/backups/equipment-YYYYMMDD-HHMMSS-ffffff.db "$env:USERPROFILE\Downloads\"
```

`YYYYMMDD...`는 실제 파일명이 아닙니다. 라파에 표시된 이름으로 바꿉니다. DB에는 학생 정보와 로그인 관련 데이터가 있으므로 공개 폴더에 올리지 마세요. `.env`, 모델, 사진·라벨은 DB 백업에 포함되지 않으며 따로 보관합니다.

### 12-3. 코드 업데이트

일반적인 코드 변경은 설치 후 [시스템 화면의 업데이트 버튼](#web-update)을 사용할 수 있습니다. 패키지·서비스 구성 변경이나 문제 복구는 아래 SSH 순서를 사용하세요.

**실행 위치: 라파 SSH 터미널 — systemd로 운영 중인 경우**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
sudo systemctl stop equipment-manager.service
python scripts/backup_db.py
git status --short
git pull --ff-only origin main
python -m pip install -r requirements-pi.txt
python serve.py --check
sudo systemctl start equipment-manager.service
curl --noproxy '*' --fail http://127.0.0.1:8080/healthz
```

각 단계가 성공한 뒤 다음으로 진행합니다. **아직 모델 없는 `mock` 운영이면 검사 명령만 `python serve.py --check --allow-mock`으로 바꾸세요.** 처음 실행 전이라 DB가 없다면 백업할 DB도 없으므로 그 단계는 건너뜁니다.

`git status`에 직접 수정한 코드가 있거나 `git pull`이 실패하면 내용을 확인하고 해결합니다. `.env`나 DB를 지우거나 `git reset --hard`로 덮어쓰는 방식으로 해결하지 마세요. Git은 코드만 갱신하고 실행 중인 Python을 자동 교체하지 않으므로 서버 재시작이 필요합니다.

서비스 구성·종료·업데이트 권한이 바뀐 버전이면 [9절 설치기](#service)를 기존 옵션과 같은 조건으로 다시 실행합니다. `.env` 값만 바꿨다면 서비스 `restart`로 반영합니다. 수동 실행 사용자는 기존 서버를 Ctrl+C로 끈 뒤 같은 업데이트·검사를 하고 [4절](#web)의 명령으로 다시 켭니다.

PC의 가져오기 코드도 별도로 업데이트합니다. PC의 Git 업데이트가 라파 코드를 바꾸거나 그 반대로 동기화되지는 않습니다.

**실행 위치: PC PowerShell — PC 프로젝트 폴더**

```powershell
git pull --ff-only origin main
python -m pip install -r requirements-photo-transfer.txt
```

### 12-4. DB 복구

복구는 **백업 시점으로 되돌리는 작업**이며 그 이후 거래는 복구한 DB에 없습니다. 아래 예시는 기본 경로 `instance/equipment.db`를 대상으로 합니다. `DATABASE`를 별도로 지정했다면 그 경로에 맞춘 복구가 필요합니다. `sqlite3` 명령은 [초기 설치](#install)에 포함되어 있습니다.

1. 웹 서버, 촬영·진단 등 DB에 접근할 수 있는 프로젝트 프로그램을 모두 종료합니다. systemd 서버는 아래 명령으로 중지하고 수동 서버도 Ctrl+C로 종료합니다.

**실행 위치: 라파 SSH 터미널 — 복구 전에 중지·기존 백업 목록 확인**

```bash
cd ~/raspberry-pi-equipment-manager
sudo systemctl stop equipment-manager.service
systemctl is-active equipment-manager.service
ls -lt backups
```

2. `inactive`이고 다른 서버가 없는지 확인합니다. 복구할 백업을 정한 다음 아래 `restore_file` 값을 **실제 파일명**으로 바꾸세요. 괄호를 포함한 블록 전체를 실행하며, 검증이 실패하면 파일 교체 전에 중단합니다.

**실행 위치: 라파 SSH 터미널 — 기본 DB 경로 전용 복구 예시**

```bash
(
    set -eu
    restore_file="backups/equipment-YYYYMMDD-HHMMSS-ffffff.db"
    test -f "$restore_file"
    restore_check=$(sqlite3 -readonly "$restore_file" 'PRAGMA integrity_check; PRAGMA foreign_key_check;')
    test "$restore_check" = "ok"
    restore_hold=$(mktemp -d backups/before-restore-XXXXXX)
    mkdir -p instance
    cp -- "$restore_file" "$restore_hold/restored.db"
    for old_file in instance/equipment.db instance/equipment.db-wal instance/equipment.db-shm; do
        if test -e "$old_file"; then
            mv -- "$old_file" "$restore_hold/"
        fi
    done
    mv -- "$restore_hold/restored.db" instance/equipment.db
    chmod 600 instance/equipment.db
    printf '복구 완료. 이전 DB 보관 위치: %s\n' "$restore_hold"
)
```

기존 DB와 WAL·SHM이 있으면 함께 별도 폴더에 보관하고 백업본을 배치합니다. [SQLite WAL 문서](https://www.sqlite.org/wal.html)에 설명된 것처럼 WAL은 DB 상태의 일부이므로, 서버 실행 중 메인 `.db` 파일만 복사하거나 새 DB에 이전 WAL을 섞지 않습니다. 교체 중 오류가 나면 서버를 시작하지 말고 출력된 오류와 `backups/before-restore-*` 파일을 확인하세요.

3. 복구 완료 메시지 뒤 서버를 시작하고 **기자재 수량, 최근 거래, 미반납, 학생 승인 상태**를 확인합니다. 백업 당시 세션 정보도 포함되므로 공유 단말에서는 로그아웃 후 다시 로그인하세요.

**실행 위치: 라파 SSH 터미널 — 복구 성공 후**

```bash
sudo systemctl start equipment-manager.service
sudo systemctl status equipment-manager.service --no-pager -l
curl --noproxy '*' --fail http://127.0.0.1:8080/healthz
```

코드 버전까지 되돌릴 때는 DB 스키마와 맞는 백업이 필요합니다. 이 프로젝트에 자동 다운그레이드·원클릭 롤백 기능은 없습니다. 운영 복구에 앞서 별도 시험 복사본에서 연습하세요.

<a id="configuration"></a>
## 13. `.env` 설정값 안내

기본값은 [`.env.example`](.env.example)와 [설정 코드](equipment_manager/config.py)를 기준으로 정리했습니다. 모든 값을 직접 추가할 필요는 없습니다. `.env`를 수정하면 서버를 재시작합니다. `.env`에 값을 쓰는 대신 이미 프로세스 환경변수로 설정된 값이 있으면 그 값이 우선할 수 있습니다.

### 계정·로그인·DB

| 항목 | 초기값 또는 요구 조건 | 용도 |
|---|---|---|
| `SECRET_KEY` | 생성 도구로 무작위 값, 32자 이상 | 세션 보호. 변경하면 기존 로그인에 영향 |
| `DEVELOPER_USERNAME` / `DEVELOPER_PASSWORD` | 서로 다른 관리자 아이디, 비밀번호 12자 이상 | 개발자 로그인 |
| `TEACHER_USERNAME` / `TEACHER_PASSWORD` | 비밀번호 예제 값 사용 금지 | 선생님 공용 로그인 |
| `DATABASE` | 프로젝트 `instance/equipment.db` | SQLite 파일. 다른 위치는 절대 경로 권장 |
| `AUTH_IDLE_SECONDS` | `900` | 미사용 세션 만료, 코드 최소 60초 |
| `AUTH_MAX_SECONDS` | `28800` | 로그인 후 최대 시간, 코드 최소 300초 |
| `SESSION_COOKIE_SECURE` | `false` | HTTPS를 구성한 경우만 `true` |
| `CSRF_ENABLED` | `true` | 배포에서는 켜 두어야 함 |
| `MAX_CONTENT_LENGTH` | `1000000` | 앱 요청 크기 제한, 바이트 |

`SESSION_COOKIE_HTTPONLY=true`, `SESSION_COOKIE_SAMESITE=Lax`는 코드의 고정 쿠키 설정입니다. 오래된 `ADMIN_USERNAME`·`ADMIN_PASSWORD`는 개발자 계정의 하위 호환용이며 새 설치에서는 역할별 항목을 사용합니다. `STATION_PIN`·`STATION_AUTH_REQUIRED`는 더 이상 사용하지 않습니다.

### 인식·카메라

| 항목 | 기본값 | 용도 |
|---|---|---|
| `DETECTOR_MODE` | `mock` | 실제 운영은 `yolo` |
| `YOLO_MODEL_PATH` | `models/best.pt` | `.pt` 파일 또는 NCNN 폴더 |
| `YOLO_IMAGE_SIZE` | `320` | 추론 입력 크기. NCNN 내보낸 크기와 맞춤 |
| `YOLO_CONFIDENCE` | `0.60` | 인식 신뢰도 기준 |
| `YOLO_FRAME_COUNT` | `5` | 한 번 인식 시 사용할 프레임 수 |
| `YOLO_MIN_VOTES` | `3` | 같은 종류 판단에 필요한 최소 표 수 |
| `YOLO_MAX_DETECTIONS` | `5` | 프레임당 탐지 후보 제한. 대여 수량 자동 계산과 무관 |
| `YOLO_CLASS_ALIASES` | `'{}'` | 모델 영문 이름 → DB 기자재명 JSON |
| `INFERENCE_THREADS` | `2` | 추론 스레드 수 |
| `GC_INTERVAL_SCANS` | `20` | 주기적 Python 자원 정리 간격 |
| `CAMERA_BACKEND` | `picamera2` | Pi 카메라. USB는 `opencv` |
| `CAMERA_INDEX` | `0` | USB 카메라 번호 |
| `CAMERA_WIDTH` / `CAMERA_HEIGHT` | `640` / `480` | 카메라 촬영 해상도 |
| `CAMERA_BUFFER_COUNT` | `2` | Pi 카메라 버퍼 수 |
| `CAMERA_WARMUP_SECONDS` | `0.5` | 카메라 준비 시간 |

카메라 방향 변경을 위한 `CAMERA_ROTATION` 같은 `.env` 설정은 현재 구현되어 있지 않습니다. 사진 전송의 `--rotation`은 PC 복사본에만 적용됩니다.

### 기자재·기한·상태·로그

| 항목 | 기본값 | 용도 |
|---|---|---|
| `DEFAULT_EQUIPMENT` | `멀티미터,아두이노,브레드보드` | 빈 DB 최초 기자재 목록 |
| `DEFAULT_QUANTITY` | `10` | 최초 수량. 실제 값으로 관리 화면에서 수정 |
| `DEFAULT_LOAN_DAYS` | `7` | 새 기자재의 초기 대여 기간 |
| `MAX_LOAN_DAYS` | `90` | 관리자 입력 상한. 0일은 당일 반납 |
| `SCAN_TOKEN_TTL_SECONDS` | `90` | 인식 결과 유효 시간 |
| `DUPLICATE_WINDOW_SECONDS` | `5` | 동일 거래 반복 차단 간격 |
| `DEVICE_NAME` | 예시 파일은 `실습실 기자재 인식 스테이션` | 표시할 장치명 |
| `HEARTBEAT_ENABLED` | `true` | 장치 상태 갱신·백그라운드 정리 |
| `HEARTBEAT_INTERVAL_SECONDS` | `15` | 상태 갱신 간격 |
| `DEVICE_OFFLINE_SECONDS` | `45` | 마지막 갱신 이후 오프라인 판단 기준 |
| `MEMORY_WARNING_MB` | `1200` | 앱 메모리 경고 기준. 강제 종료 한도가 아님 |
| `LOG_LEVEL` | `INFO` | 기본 로그 수준 |
| `ERROR_LOG_PATH` | `instance/errors.log` | 앱 오류 로그 경로 |
| `ERROR_LOG_MAX_BYTES` | `1000000` | 로그 파일 회전 크기 |
| `ERROR_LOG_BACKUP_COUNT` | `2` | 회전 로그 보관 수, 코드에서 1~5개로 제한 |
| `ERROR_LOG_DISPLAY_BYTES` | `65536` | 개발자 화면에 읽어 표시할 최대 분량 |

### 선택 하드웨어·서비스 전용 값

| 항목 | 기본값 | 용도 |
|---|---|---|
| `GPIO_ENABLED` | `false` | LED·부저 사용. 배선 준비 후 활성화 |
| `GPIO_GREEN_PIN` | `17` | 초록 LED의 BCM GPIO 번호 |
| `GPIO_RED_PIN` | `27` | 빨강 LED의 BCM GPIO 번호 |
| `GPIO_BUZZER_PIN` | `22` | 부저의 BCM GPIO 번호 |
| `POWER_OFF_ENABLED` | `false`, 설치기가 지정 | 종료 기능 표시·사용 허용 |
| `PROGRAM_UPDATE_ENABLED` | `false`, 설치기가 지정 | Git 업데이트·재시작 기능 표시·사용 허용 |
| `SYSTEMD_SERVICE_MANAGED` | `false`, 서비스에서 `true` | 서비스가 관리하는 프로그램인지 구분 |

GPIO 번호는 커넥터의 물리 핀 번호와 다릅니다. GPIO를 사용하지 않으면 기본 `false`로 둡니다. 종료 관련 값은 설치기가 생성한 systemd 환경에서 설정하므로 `.env`에 `true`만 적어 기능을 설치할 수는 없습니다.

2GB Pi를 위해 기본 서버는 프로세스 1개, 웹 스레드 2개, 동시 추론 1개를 사용합니다. Waitress 연결 32개·요청 본문 1MB 등은 [배포 코드](equipment_manager/deployment.py), 서비스의 `MemoryHigh=1300M`, `MemoryMax=1600M`, `TasksMax=64`는 [서비스 템플릿](deploy/equipment-manager.service)에 있습니다. 이는 `.env` 설정이 아니며 메모리 한도는 자동 확장이나 누수 해결을 대신하지 않습니다.

<a id="troubleshooting"></a>
## 14. 문제 해결

오류 메시지 전체와 **PC/라파 중 어디서 실행했는지**, 실행 명령, 현재 폴더를 먼저 확인합니다. `.env` 내용·비밀번호가 보이는 화면은 공유하지 마세요. 서비스 오류는 라파에서 `journalctl -u equipment-manager.service -n 80 --no-pager`로 확인합니다.

### 설치·서버 실행

| 증상 | 해결 순서 |
|---|---|
| `can't open file ...` | 프로젝트 폴더로 이동. PC의 가져오기 코드와 라파의 촬영 코드를 구분 |
| `No module named ...` | 현재 Python 환경 확인. 라파는 `source .venv/bin/activate` 후 `requirements-pi.txt`, PC 전송은 `requirements-photo-transfer.txt` 설치 |
| `externally-managed-environment` | 시스템 Python에 pip로 설치하지 말고 프로젝트 가상환경 사용 |
| `.env가 없습니다` | 기존 설정 위치 확인. 새 설치일 때만 `create_env.py` 실행 |
| 관리자 비밀번호·SECRET_KEY 검사 실패 | `.env.example`의 예제 값을 그대로 쓰지 않았는지 확인 |
| `Address already in use` | 8080을 쓰는 수동 서버·서비스 중복 확인. 기존 서버 종료 후 하나만 실행 |
| 서비스 설치에서 일반 사용자 오류 | root 직접 로그인이 아니라 일반 사용자 SSH에서 `sudo bash deploy/install_service.sh ...` 실행 |
| 서비스가 `failed` / 재시작 반복 | 로그에서 `.env`, 모델, 권한, 의존성, 메모리 제한 원인 확인 |
| 종료 버튼 비활성화·요청 거부 | polkit 설치와 `--enable-poweroff` 설치 확인. 프로그램만 종료는 systemd 서버에서 사용 |
| 재부팅 뒤 시작 안 됨 | `systemctl is-enabled`, `is-active`, 서비스 로그 확인. 수동 실행은 자동 시작 등록이 아님 |

### 카메라·모델

| 증상 | 해결 순서 |
|---|---|
| 카메라 사용 중 | 서버·촬영·진단을 동시에 실행하지 않았는지 확인 |
| Pi 카메라가 목록에 없음 | 안전 종료·전원 분리 후 케이블 방향과 연결 확인. 전원이 켜진 채 리본 케이블 탈착하지 않기 |
| `Camera frontend has timed out` | 목록에 보여도 프레임이 안 오는 상태일 수 있음. 프로그램 종료·안전 종료 뒤 연결 점검 |
| USB 카메라가 안 열림 | `CAMERA_BACKEND=opencv`, 실제 장치 번호·권한 확인 |
| `numpy.dtype size changed` | 오류를 낸 라이브러리 확인. 아래 simplejpeg 사례와 같은 경우에만 해당 조치 적용 |
| `YOLO 모델을 찾을 수 없습니다` | `.env` 경로와 파일·폴더 존재·권한 확인. NCNN ZIP은 먼저 풀기 |
| 모델은 인식하지만 DB 기자재를 못 찾음 | 모델 클래스 → `YOLO_CLASS_ALIASES` → 관리자 등록 이름을 차례로 비교 |
| 물체를 못 찾거나 다른 종류로 인식 | 라벨·조명·초점·거리·입력 방향 점검. 신뢰도만 무작정 낮추지 않기 |
| 사진 색상이 이상함 | 촬영 코드 업데이트 후 새 사진과 비교. 구버전 사진을 확인 없이 학습에 섞지 않기 |
| RSS 증가로 메모리 검사 실패 | 측정값·실패 횟수·모델·해상도 보관. 작은 입력·nano/NCNN을 실제 비교하고 재검사 |
| 프로세스가 `Killed`로 종료 | 서비스·커널 로그에서 메모리 부족 확인. 임계값만 올리기 전에 중복 프로세스·모델 크기 확인 |

2026-09-23 장치 점검에서는 가상환경 NumPy와 시스템 simplejpeg의 ABI 충돌을 가상환경의 simplejpeg 업그레이드로 해결했습니다. 최신 `requirements-pi.txt`에도 이 의존성을 포함합니다. **동일한 simplejpeg 오류일 때만** 아래 명령을 사용합니다.

**실행 위치: 라파 SSH 터미널 — 프로젝트 폴더**

```bash
.venv/bin/python -m pip install --only-binary=:all: --no-deps "simplejpeg>=1.9,<2"
```

### 로그인·수량·DB

| 증상 | 해결 순서 |
|---|---|
| teacher/developer로 로그인 안 됨 | `/admin/login` 사용, 실제 `.env`의 계정 확인, 수정 후 서버 재시작. `.env.example`은 로그인 파일이 아님 |
| 학생 가입 후 로그인 안 됨 | 관리자가 본인 확인 후 승인했는지 확인 |
| HTTP에서 로그인 직후 풀림 | `SESSION_COOKIE_SECURE=false`, 기기 시간, 서로 다른 서버·포트 혼용 여부 확인 |
| 요청 횟수 제한 | 표시된 대기 시간 뒤 재시도. 반복 클릭으로 해결되지 않음 |
| 인식 결과 만료 | 새로 인식. 저장 응답을 못 받았다면 거래 내역을 먼저 확인 |
| 사용 가능 수량 수정이 거절됨 | 실제 미반납과 전체 수량의 관계 확인. 거래 취소와 수량 수정은 구분 |
| `FOREIGN KEY constraint failed` / heartbeat 오류 | DB 백업 후 코드 업데이트. 계속되면 실패 로그와 버전 확인. DB·거래·스캔 테이블을 임의 삭제하지 않기 |
| DB 잠김 / 권한 오류 | 같은 DB의 여러 서버, 종료 안 된 진단, 실제 실행 사용자·파일 권한 확인 |

### 사진 전송·라벨링

| 증상 | 해결 순서 |
|---|---|
| PC의 `python`이 안 됨 | `py --version` 확인. 둘 다 없으면 Python 설치 |
| SSH 연결 시간 초과 | 전원·네트워크·현재 IP 확인. [네트워크 점검](#network) 참고 |
| `not found in known_hosts` | PC에서 먼저 일반 `ssh 사용자명@IP`로 접속해 장치 확인 |
| SSH 장치 키 불일치 | IP 재배정·OS 재설치 여부 확인. 확인 없이 기존 키를 지우지 않기 |
| `Authentication failed` | SSH 계정 확인. 다른 사용자라면 `--user` 지정 |
| 사진 경로가 없음 | 실제 촬영 완료 여부와 프로젝트 경로 확인. 필요하면 `--remote-project /실제/경로` 사용 |
| 기존 출력 폴더라며 중단 | 새 폴더를 지정하거나 기본 자동 생성 위치 사용 |
| JSON만 있고 TXT는 없음 | [YOLO 내보내기](#labeling-export)를 별도로 수행 |
| TXT 번호에 대응하는 물체가 다름 | 모든 회차의 `classes.txt`와 `data.yaml`의 `names` 순서 비교 |
| 사진만 있는데 학습이 안 됨 | 사진별 라벨·데이터 분리·YAML 준비 여부 확인 |

<a id="development"></a>
## 15. PC 개발·자동 검사·프로젝트 구조

### 15-1. PC에서 웹 화면만 실행

PC에서 실행하면 **PC의 별도 DB**를 사용합니다. 라파의 운영 데이터가 자동으로 표시되지 않습니다. 실제 운영 화면을 보려면 PC 서버를 켜지 않고 라파 웹 주소로 접속하세요.

PC 프로젝트 폴더가 없다면 먼저 저장소를 복제합니다. 이미 있으면 그 폴더에서 시작하세요. 아래 예시는 가상환경 Python을 직접 호출하므로 PowerShell 실행 정책 변경이 필요하지 않습니다.

**실행 위치: PC PowerShell — 프로젝트 폴더, PC용 환경 최초 준비**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-photo-transfer.txt
```

**실행 위치: PC PowerShell — 이 PC 프로젝트에 `.env`가 없을 때만**

```powershell
.\.venv\Scripts\python.exe scripts/create_env.py
```

이미 `.env`가 있으면 그대로 보존합니다. 이 PC의 웹 확인용 설정은 `DETECTOR_MODE=mock`, `GPIO_ENABLED=false`여야 합니다. 라파의 실제 인식용 설정과 혼동하지 마세요.

**실행 위치: PC PowerShell — PC 웹 서버 실행**

```powershell
.\.venv\Scripts\python.exe serve.py --check --allow-mock
.\.venv\Scripts\python.exe serve.py --allow-mock
```

PC 브라우저에서 `http://127.0.0.1:8080`을 엽니다. 종료는 해당 PowerShell의 Ctrl+C입니다. PC 가상환경에 사진 전송 패키지를 설치했다면 사진 가져오기도 같은 `.\.venv\Scripts\python.exe`로 실행할 수 있습니다.

### 15-2. 자동 검사 명령

**실행 위치: PC PowerShell — 위 PC 가상환경 준비 후**

```powershell
.\.venv\Scripts\python.exe -m compileall -q equipment_manager scripts deploy tests wsgi.py serve.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**실행 위치: PC PowerShell — Node.js가 설치된 경우**

```powershell
node --test tests/test_frontend.cjs tests/test_dashboard.cjs tests/test_equipment_editor.cjs tests/test_poweroff_policy.cjs tests/test_capture_preview.cjs
```

서버 운영에는 Node.js가 필요하지 않습니다. 테스트는 임시 DB·모의 장치를 사용하며, 사진 회전 검사는 PC용 Pillow가 필요합니다. Linux/systemd 관련 일부 검사는 Windows에서 제외됩니다. [GitHub Actions](.github/workflows/tests.yml)는 Linux에서 Python·화면·배포 스크립트 검사를 수행합니다.

**실행 위치: PC PowerShell — 웹 처리 반복 점검, 운영 DB 사용 안 함**

```powershell
.\.venv\Scripts\python.exe tests/test_resource_soak.py --cycles 500 --warmup 100
```

사진 반복 검사는 실제 카메라 대신 합성 이미지를 쓰지만 OpenCV·NumPy가 추가로 필요합니다.

**실행 위치: PC PowerShell — 선택 사진 반복 검사**

```powershell
.\.venv\Scripts\python.exe -m pip install opencv-python numpy
.\.venv\Scripts\python.exe tests/test_capture_preview_soak.py --cycles 1000 --warmup 100
```

**확인된 범위:** 2026-09-26 PC 기준 Python 221개 중 219개 통과·2개 환경 제외, 화면 검사 32개 통과. 실제 SSH 사진 3장 전송·180도 회전도 확인했습니다. 이는 실제 Pi 카메라·YOLO의 장시간 운영 검증을 대체하지 않습니다. [전체 코드 점검 보고서](docs/REFACTORING_AUDIT_2026-09-26.md)와 [과거 검증 기록](docs/VALIDATION_HISTORY.md)에 당시 조건·측정값을 보관합니다.

### 15-3. 주요 파일과 도구

| 경로 | 역할 |
|---|---|
| `serve.py` | 설정 검사 후 Waitress 실행·종료 관리 |
| `equipment_manager/` | Flask 앱, DB, 권한, 기자재, 인식, 하드웨어 |
| `equipment_manager/routes/` | 현황·계정·대여·관리·개발자 기능 |
| `equipment_manager/templates/`, `static/` | 화면·스타일·브라우저 요청 처리 |
| `deploy/` | systemd 서비스 설치·종료 권한 |
| `deploy/update_runner.py` | 설치 후 별도 systemd 작업으로 Git 업데이트·DB 백업·재시작 |
| `scripts/` | 환경 생성, 사진 촬영·전송, 장치 진단, 백업 |
| `training/` | 클래스 목록, 데이터셋 YAML, Colab 노트북 |
| `tests/` | 서버·DB·카메라·화면·종료·자원 회귀 검사 |
| `docs/` | 점검 보고서·검증 이력 |

| 도구 | 실행할 곳 | 역할 |
|---|---|---|
| `create_env.py` | 초기 설치 기기 | 기존 파일을 덮어쓰지 않고 `.env` 생성 |
| `setup_accounts.py` | 기존 `.env`가 있는 기기 | 이전 관리자 설정에 역할별 계정 보완 |
| `capture_samples.py` | 카메라 연결 라파 | `--manual` 엔터 촬영, 일정 간격 자동 촬영 |
| `download_photos.py` | PC | SSH/SFTP 복사·180도 회전. `--help`로 옵션 확인 |
| `pi_diagnostics.py` | 라파 | 실제 모델·카메라 점검 |
| `memory_soak_test.py` | 라파 | 실제 인식 반복·메모리 추이 확인 |
| `test_model_image.py` | 모델 실행 환경 | 사진 한 장의 클래스·신뢰도·결과 이미지 확인 |
| `network_info.py` | 서버가 실행되는 기기 | 웹 접속 주소 표시 |
| `backup_db.py` | 운영 DB가 있는 기기 | SQLite 백업·기본 무결성 검사 |

`capture_samples.py --preview`는 코드에 남아 있는 선택 기능입니다. 현재 사용 순서는 **미리보기 없이 엔터 촬영**이며 선택 기능·자동 촬영 상세는 [촬영 안내](training/PHOTO_CAPTURE.md)에 분리했습니다. [Ubuntu YOLO 참고 문서](YOLO_객체인식_우분투_가이드.md)는 별도 일반 실습 자료이며 이 프로젝트의 실행 절차는 본 README를 따릅니다.

<a id="release"></a>
## 16. 학교 배포 전 확인

- [ ] `serve.py --check` 통과. 실제 운영에서는 `--allow-mock` 사용 안 함.
- [ ] 실제 기자재 클래스·웹 등록 이름·전체 수량·대여 기간이 일치함.
- [ ] 회전된 학습 사진과 실제 카메라 입력 방향을 맞추고 시험함.
- [ ] 실제 카메라 진단·반복 인식 메모리 검사를 통과함.
- [ ] 여러 조명·거리·각도에서 인식 결과를 사람이 확인함.
- [ ] 학생 가입 승인·로그인·본인 내역·비밀번호 재설정을 시험함.
- [ ] 대여·반납·연체 차단·잘못된 거래 취소를 시험함.
- [ ] 선생님·개발자 권한 차이와 공용 단말 로그아웃을 확인함.
- [ ] DB 백업을 라파 밖에 보관하고 시험 복사본에서 복구를 확인함.
- [ ] 같은 교실·다른 교실·다른 층에서 웹 접속을 확인함.
- [ ] 라파 주소 유지 방식과 학교 네트워크 접근을 담당자와 확인함.
- [ ] 재부팅 후 서비스 자동 실행, 필요 시 개발자 종료 기능을 확인함.

## 추가 문서

- [촬영 선택 옵션·PC 전송](training/PHOTO_CAPTURE.md)
- [데이터셋 구성](training/README.md) · [클래스 목록](training/classes.txt) · [YAML 예시](training/dataset_example.yaml)
- [Colab 학습 노트북](training/YOLO_기자재_학습_Colab.ipynb)
- [리팩토링·자원 점검 보고서](docs/REFACTORING_AUDIT_2026-09-26.md)
- [과거 검증 기록](docs/VALIDATION_HISTORY.md)
