# AI 실습 기자재 대여·반납 시스템

카메라 앞에 기자재를 놓으면 Raspberry Pi가 기자재의 **종류**를 인식합니다. 학생은 학번과 수량을 입력해 대여하거나 반납하고, 다른 PC나 스마트폰에서는 현재 남은 수량을 웹사이트로 확인할 수 있습니다. 반납 예정일은 관리자가 기자재마다 설정한 대여 기간으로 자동 계산됩니다. 반납 기한이 지나면 해당 학번은 연체 기자재를 모두 반납할 때까지 새로 대여할 수 없습니다.

예를 들어 멀티미터 10개 중 2개를 대여하면 웹사이트에는 다음처럼 표시됩니다.

```text
멀티미터
전체 10개 / 대여 중 2개 / 사용 가능 8개
```

개별 멀티미터의 고유번호까지 구분하지는 않습니다. 멀티미터, 아두이노, 브레드보드처럼 **큰 종류와 수량**만 관리합니다.

## 어디서부터 읽으면 되나요?

- Raspberry Pi를 처음 켜는 단계라면 [1부부터](#1부-raspberry-pi-처음-준비하기) 순서대로 진행합니다.
- Pi OS와 카메라가 이미 준비됐다면 [2부부터](#2부-카메라가-정상인지-확인하기) 시작합니다.
- 학습 모델 없이 웹 화면만 보고 싶다면 [5부](#5부-모델이-없을-때-웹사이트부터-확인하기)를 봅니다.
- `best.pt` 또는 NCNN 모델이 준비됐다면 [6부](#6부-학습-모델을-raspberry-pi로-복사하기)부터 실제 인식을 설정합니다.
- 오류가 발생했다면 화면의 오류 문장을 복사한 뒤 [문제 해결](#문제-해결)에서 찾습니다.

실제 동작까지의 전체 순서는 다음과 같습니다.

```text
Pi OS 설치 → 카메라 시험 → 프로젝트 설치 → 비밀번호 설정
→ 모델 복사 → 실제 모드 설정 → 장치 진단 → 메모리 검사
→ 웹 실행 → 부팅 자동 실행 → 학교 네트워크 접속 확인
```

---

## 처음 시작하는 사람이 꼭 알아야 할 것

이 문서에 나오는 용어는 다음 뜻입니다.

- **Raspberry Pi 또는 Pi**: 카메라와 웹 서버가 연결될 작은 컴퓨터입니다.
- **터미널**: 명령어를 입력하는 검은 화면입니다.
- **PowerShell**: Windows에서 사용하는 터미널입니다.
- **YOLO 모델**: 사진을 보고 기자재 종류를 판단하는 학습 파일입니다.
- **`.env`**: 비밀번호, 카메라 종류, 모델 위치 등을 적는 설정 파일입니다.
- **IP 주소**: 다른 기기에서 Raspberry Pi 웹사이트에 접속할 때 사용하는 주소입니다.

## 서버와 DB는 무엇을 사용하나요?

이 프로젝트는 다음 구조로 동작합니다.

```text
학교 PC·스마트폰의 웹 브라우저
              │
              │  http://Pi주소:8080
              ▼
     Waitress 웹 서버
     └─ 8080 포트를 열고 웹 요청을 받음
              │
              ▼
        Flask 프로그램
        ├─ 로그인 확인
        ├─ 대여·반납 처리
        ├─ 관리자 화면 처리
        └─ YOLO와 카메라 실행
              │
              ▼
        SQLite 데이터베이스
        └─ 기자재 수량과 거래 기록 저장
```

Flask만 단독으로 실행하는 개발 서버를 학교 운영에 사용하는 것은 아닙니다. Flask는 웹사이트의 기능을 구현하는 프로그램이고, 실제로 8080 포트를 열어 여러 기기의 요청을 받는 운영용 웹 서버는 **Waitress**입니다.

DB는 **SQLite**를 사용합니다. 별도의 MySQL이나 PostgreSQL 서버를 설치할 필요가 없으며, 기본 DB 파일은 Pi 안의 다음 위치에 생깁니다.

```text
raspberry-pi-equipment-manager/instance/equipment.db
```

학교 PC마다 DB가 따로 생기는 것이 아닙니다. 모든 PC와 스마트폰이 Raspberry Pi에 접속하고, Raspberry Pi 안의 `equipment.db` 하나를 함께 사용합니다.

```text
교실 PC ─┐
학생 폰 ─┼─→ Raspberry Pi ─→ equipment.db 하나
교사 PC ─┘
```

이 과제처럼 Raspberry Pi 한 대가 인식과 대여·반납을 처리하는 규모에는 SQLite가 단순하고 메모리 사용량도 적어 적합합니다. DB는 WAL 모드로 실행하여 현황 조회 중에도 대여·반납 저장이 가능한 한 원활하게 처리되도록 구성했습니다.

나중에 Raspberry Pi 인식 장치를 여러 대 설치하고 모든 장치가 같은 재고를 동시에 수정해야 한다면 그때는 중앙 서버의 PostgreSQL 같은 DB로 변경하는 것이 좋습니다. 현재 한 대 구성에서는 SQLite를 그대로 사용합니다.

명령어 상자 안의 내용을 한 줄씩 복사하고 `Enter`를 누르면 됩니다. 명령 앞에 보이는 `$`나 `>` 표시는 입력하지 않습니다. 이 문서의 모든 명령어 상자 바로 위에는 실행할 기기를 다음처럼 표시했습니다.

| 표시 | 어디에서 실행하나요? |
|---|---|
| `실행 위치: Windows PC의 PowerShell` | Windows 시작 메뉴에서 PowerShell을 열어 입력 |
| `실행 위치: Raspberry Pi 터미널` | PC에서 Pi에 SSH로 접속한 뒤 나타나는 Pi 명령줄에 입력 |
| `편집 위치: Raspberry Pi의 .env 파일` | Pi 터미널에서 `nano .env`를 연 화면에 작성 |
| `확인 위치: Google Colab` | 웹 브라우저에서 연 Colab 학습 노트북에서 확인 |

명령어가 여러 줄 들어 있는 상자는 위에서 아래 순서대로 모두 같은 위치에서 실행합니다.

`<PI_USER>`, `<PI_IP>`, `<모델이_있는_경로>`처럼 꺾쇠괄호로 표시한 부분은 그대로 입력하지 말고 자신의 값으로 바꿉니다.

예를 들어 Pi 사용자명이 `equipment`, IP가 `192.168.0.25`라면 다음과 같습니다.

> **실행 위치: Windows PC의 PowerShell**

```powershell
ssh equipment@192.168.0.25
```

비밀번호를 입력할 때 화면에 글자나 별표가 표시되지 않는 것은 정상입니다. 비밀번호를 입력하고 `Enter`를 누르면 됩니다.

---

## 준비물

필수 준비물:

- Raspberry Pi 4B RAM 2GB
- Raspberry Pi용 전원 어댑터
- microSD 카드 16GB 이상
- Raspberry Pi 공식 카메라 또는 USB 웹캠
- microSD 카드를 읽을 수 있는 Windows PC
- 같은 네트워크에 연결할 공유기 또는 Wi-Fi
- 직접 학습한 YOLO 모델

YOLO 모델은 다음 중 하나가 필요합니다.

```text
best.pt
```

또는:

```text
best_ncnn_model 폴더
```

모델이 아직 없어도 웹사이트와 대여·반납 기능은 실행할 수 있습니다. 하지만 **실제 카메라 객체 인식은 학습 모델이 준비된 뒤에만 동작합니다.**

---

# 1부. Raspberry Pi 처음 준비하기

이미 Raspberry Pi OS가 설치되어 있고 터미널을 사용할 수 있다면 [2부로 이동](#2부-카메라가-정상인지-확인하기)합니다.

## 1-1. Raspberry Pi OS 설치

Windows PC에서 [Raspberry Pi Imager](https://www.raspberrypi.com/software/)를 설치하고 실행합니다.

Imager에서 다음과 같이 선택합니다.

1. 장치: `Raspberry Pi 4`
2. 운영체제: `Raspberry Pi OS Lite (64-bit)`
3. 저장 장치: 준비한 microSD 카드

운영체제 설정 화면에서는 다음 항목을 입력합니다.

- 호스트 이름: `equipment-pi`
- 사용자 이름: 원하는 영문 이름. 예: `equipment`
- 비밀번호: 잊어버리지 않을 비밀번호
- Wi-Fi 이름과 비밀번호
- 국가: `KR`
- 시간대: `Asia/Seoul`
- SSH: 활성화
- SSH 인증: 비밀번호 인증

설정을 저장하고 microSD 카드에 운영체제를 기록합니다. Raspberry Pi 공식 문서에서도 화면 없는 설치를 할 때 Imager에서 사용자, Wi-Fi, 호스트 이름과 SSH를 미리 설정할 수 있다고 안내합니다.

## 1-2. 카메라와 microSD 카드 연결

1. Raspberry Pi 전원선을 뽑습니다.
2. 카메라 리본 케이블을 카메라 단자에 연결합니다.
3. microSD 카드를 삽입합니다.
4. 가능하면 유선 LAN도 연결합니다.
5. 마지막에 전원을 연결합니다.
6. 첫 부팅이 끝나도록 2~3분 기다립니다.

카메라 케이블은 반드시 전원이 꺼진 상태에서 연결하는 것이 안전합니다.

## 1-3. Windows에서 Pi에 접속

Windows에서 시작 메뉴를 열고 `PowerShell`을 실행합니다.

사용자 이름을 Imager에서 정한 이름으로 바꿔 입력합니다.

> **실행 위치: Windows PC의 PowerShell**

```powershell
ssh <PI_USER>@equipment-pi.local
```

예시:

> **실행 위치: Windows PC의 PowerShell**

```powershell
ssh equipment@equipment-pi.local
```

처음 접속할 때 연결을 계속할지 묻는 메시지가 나오면 다음을 입력합니다.

> **입력 위치: 위 SSH 명령을 실행한 Windows PC의 PowerShell**

```text
yes
```

그다음 Imager에서 설정한 Pi 비밀번호를 입력합니다.

`equipment-pi.local`로 연결되지 않으면 공유기 관리 화면에서 Pi의 IP를 확인한 뒤 다음처럼 접속합니다.

> **실행 위치: Windows PC의 PowerShell**

```powershell
ssh <PI_USER>@<PI_IP>
```

로그인 후 다음과 비슷한 줄이 보이면 Pi 터미널에 들어온 것입니다.

```text
equipment@equipment-pi:~ $
```

이제부터 명령어 위에 **Raspberry Pi 터미널**이라고 표시된 내용은 이 Pi 명령줄에 입력합니다. **Windows PC의 PowerShell**이라고 표시된 명령은 SSH 안이 아니라 Windows PowerShell 창에서 실행합니다.

> 학교 Wi-Fi는 기기끼리 통신을 차단할 수 있습니다. 처음 설치할 때는 집 공유기나 휴대전화 핫스팟을 이용하면 문제를 구분하기 쉽습니다.

---

# 2부. 카메라가 정상인지 확인하기

Pi 터미널에서 프로그램 목록을 갱신하고 필요한 프로그램을 설치합니다.

> **실행 위치: Raspberry Pi 터미널(SSH 접속 후)**

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3-venv python3-picamera2 python3-opencv rpicam-apps
```

설치에는 몇 분 이상 걸릴 수 있습니다. 오류 없이 다시 입력할 수 있는 줄이 나타나면 완료된 것입니다.

공식 Raspberry Pi 카메라라면 다음 명령으로 사진을 찍습니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
rpicam-still --output camera-test.jpg
```

촬영 파일이 생겼는지 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
ls -lh camera-test.jpg
```

다음처럼 파일 크기가 표시되면 카메라가 동작한 것입니다.

```text
-rw-r--r-- 1 equipment equipment 2.1M ... camera-test.jpg
```

Raspberry Pi OS Bookworm 이후 버전에서는 카메라 명령이 `libcamera-*`가 아니라 `rpicam-*`로 시작합니다.

USB 웹캠을 사용할 경우 다음 명령으로 장치가 있는지 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
ls -l /dev/video*
```

`/dev/video0`이 보이면 보통 카메라 번호는 `0`입니다.

카메라 시험이 실패했다면 프로그램 설치를 계속하기 전에 [카메라 문제 해결](#카메라를-찾지-못합니다) 항목을 먼저 확인합니다.

---

# 3부. 프로젝트 내려받기

## 3-1. GitHub 저장소 복제

Pi 터미널에서 홈 폴더로 이동합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~
```

프로젝트를 내려받습니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
git clone https://github.com/hapbii/raspberry-pi-equipment-manager.git
```

현재 저장소는 비공개입니다. GitHub 로그인을 요구하면 다음 값을 입력합니다.

- `Username`: 자신의 GitHub 사용자명
- `Password`: GitHub 계정 비밀번호가 아니라 Personal Access Token

토큰은 GitHub의 [Personal Access Token 안내](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)를 따라 만듭니다. 토큰에는 이 저장소를 읽을 수 있는 최소 권한만 주고, 토큰을 명령어나 소스 파일에 직접 적지 않습니다.

성공하면 폴더로 이동합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
```

파일이 내려받아졌는지 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
ls
```

다음 이름들이 보이면 정상입니다.

```text
README.md  equipment_manager  scripts  training  requirements-pi.txt
```

## 3-2. 프로젝트 전용 Python 환경 만들기

다음 명령을 차례대로 실행합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더)**

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-pi.txt
```

패키지 설치는 Raspberry Pi 4에서 오래 걸릴 수 있습니다. 중간에 전원을 끄지 않습니다.

명령줄 앞에 `(.venv)`가 보이면 프로젝트 전용 환경이 활성화된 것입니다.

```text
(.venv) equipment@equipment-pi:~/raspberry-pi-equipment-manager $
```

나중에 새 터미널을 열었을 때 `(.venv)`가 없다면 프로젝트 폴더에서 다음 명령을 다시 실행합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더)**

```bash
source .venv/bin/activate
```

---

# 4부. 설정 파일 만들기

프로젝트 폴더와 가상환경이 활성화된 상태에서 실행합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더, 가상환경 활성화 후)**

```bash
python scripts/create_env.py
```

다음 정보가 출력됩니다.

- `.env` 파일 생성 위치
- 개발자 관리자 아이디와 비밀번호
- 선생님 관리자 아이디와 비밀번호
- 스테이션 PIN(PIN 보호를 켤 때만 사용)

두 계정의 아이디와 비밀번호를 각각 안전한 곳에 기록합니다. 개발자 계정은 모든 관리 기능과 시스템 진단 화면을 사용할 수 있고, 선생님 계정은 재고·미반납·거래 관리 기능만 사용할 수 있습니다. 기본 설정에서는 대여·반납 화면에 PIN 없이 바로 들어갈 수 있습니다.

| 계정 | 재고·거래 관리 | 대여·반납 | 시스템 진단 |
|---|---:|---:|---:|
| 선생님 관리자 | 가능 | 공개 설정이면 가능 | 접근 불가 |
| 개발자 관리자 | 가능 | 항상 가능 | 가능 |

두 계정 모두 기자재 종류를 추가·수정·제거할 수 있습니다. 최근 거래를 영구 삭제하는 기능만 개발자 계정으로 제한됩니다.

대여·반납 화면도 PIN으로 보호하고 싶다면 `.env`에서 `STATION_AUTH_REQUIRED=false`를 `true`로 변경하고, 생성할 때 출력된 스테이션 PIN을 사용합니다. 학교 내부망의 여러 사람이 웹사이트에 접속할 수 있으므로, 장난이나 잘못된 대여·반납 입력이 걱정될 때만 PIN 보호를 켜면 됩니다.

`.env`는 비밀번호가 들어 있으므로 다른 사람에게 보내거나 GitHub에 올리지 않습니다.

이전 버전에서 이미 `.env`를 만든 경우에는 기존 파일을 지우지 말고 다음 명령을 실행합니다. 안전하게 생성된 기존 관리자 비밀번호는 개발자 계정에 이어서 사용하고, 선생님 계정은 새 비밀번호를 자동으로 만듭니다. 기존 비밀번호가 `admin1234`라면 개발자 비밀번호도 새로 만듭니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더)**

```bash
python scripts/setup_accounts.py
```

화면에 개발자와 선생님 계정이 각각 출력됩니다. 이 명령은 없는 항목만 추가하므로 여러 번 실행해도 기존 비밀번호를 바꾸거나 중복으로 추가하지 않습니다. 계정 이름을 바꾸려면 `.env`의 `DEVELOPER_USERNAME` 또는 `TEACHER_USERNAME`을 수정합니다. 실행 후에는 서버나 서비스를 다시 시작해야 합니다.

---

# 5부. 모델이 없을 때 웹사이트부터 확인하기

모델이 아직 없다면 기본 `mock` 모드로 웹사이트와 대여·반납을 먼저 확인할 수 있습니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더, 가상환경 활성화 후)**

```bash
python -m waitress --listen=0.0.0.0:8080 --threads=2 wsgi:app
```

다음 메시지가 보이면 웹 서버가 실행된 것입니다.

```text
Serving on http://0.0.0.0:8080
```

웹 서버를 실행한 터미널은 그대로 둡니다. 같은 네트워크의 PC나 스마트폰에서 다음 주소를 엽니다.

```text
http://equipment-pi.local:8080
```

접속되지 않으면 Pi에서 `hostname -I`를 실행해 IP를 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
hostname -I
```

예를 들어 `192.168.0.25`가 출력되면 브라우저 주소는 다음과 같습니다.

```text
http://192.168.0.25:8080
```

서버를 종료할 때는 Pi 터미널에서 `Ctrl+C`를 누릅니다.

`mock` 모드는 화면에서 기자재를 직접 선택해 인식 결과를 흉내 냅니다. 카메라가 실제로 판단하는 모드는 아닙니다.

관리자 화면은 `http://<PI_IP>:8080/admin/login`에서 접속합니다. 선생님은 `.env`의 `TEACHER_USERNAME`과 `TEACHER_PASSWORD`, 개발자는 `DEVELOPER_USERNAME`과 `DEVELOPER_PASSWORD`를 입력합니다. 개발자 계정으로 로그인하면 상단에 `시스템` 메뉴가 추가됩니다. 대여·반납 화면은 기본 설정에서 `http://<PI_IP>:8080/scan`으로 바로 접속됩니다.

---

# 6부. 학습 모델을 Raspberry Pi로 복사하기

이미 모델이 Pi의 `models` 폴더에 있다면 [7부로 이동](#7부-실제-카메라-인식-모드로-변경하기)합니다.

Windows PC에서 모델이 들어 있는 폴더를 엽니다. 폴더의 빈 곳에서 `Shift`를 누른 채 마우스 오른쪽 버튼을 누르고 PowerShell 또는 터미널을 엽니다.

## 6-1. `best.pt`를 복사하는 경우

Windows PowerShell에서 실행합니다.

> **실행 위치: Windows PC의 PowerShell(모델 파일이 있는 폴더)**

```powershell
scp "<모델이_있는_경로>\best.pt" <PI_USER>@equipment-pi.local:~/raspberry-pi-equipment-manager/models/
```

예시:

> **실행 위치: Windows PC의 PowerShell**

```powershell
scp "C:\Users\student\Downloads\best.pt" equipment@equipment-pi.local:~/raspberry-pi-equipment-manager/models/
```

## 6-2. NCNN 모델 폴더를 복사하는 경우

> **실행 위치: Windows PC의 PowerShell(모델 폴더가 있는 위치)**

```powershell
scp -r "<모델이_있는_경로>\best_ncnn_model" <PI_USER>@equipment-pi.local:~/raspberry-pi-equipment-manager/models/
```

예시:

> **실행 위치: Windows PC의 PowerShell**

```powershell
scp -r "C:\Users\student\Downloads\best_ncnn_model" equipment@equipment-pi.local:~/raspberry-pi-equipment-manager/models/
```

Pi 비밀번호를 입력한 뒤 복사가 끝날 때까지 기다립니다.

Pi 터미널로 돌아가 모델을 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
ls -la models
```

`best.pt` 또는 `best_ncnn_model`이 보이면 복사된 것입니다.

> NCNN 모델은 Raspberry Pi CPU에서 속도를 줄이는 선택지가 될 수 있습니다. 같은 사진으로 `best.pt`와 NCNN의 정확도와 속도를 비교한 뒤 선택합니다.

---

# 7부. 실제 카메라 인식 모드로 변경하기

Pi 터미널에서 설정 파일을 엽니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
nano .env
```

방향키로 이동해 아래 항목을 찾고 수정합니다.

## 7-1. NCNN 모델과 공식 Pi 카메라를 사용하는 설정

> **편집 위치: Raspberry Pi의 `.env` 파일(nano 화면)**

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
DEFAULT_LOAN_DAYS=7
MAX_LOAN_DAYS=90
MEMORY_WARNING_MB=1200
GPIO_ENABLED=false
```

`DEFAULT_LOAN_DAYS`는 처음 만들어지는 기자재와 관리자 화면에서 새 기자재를 추가할 때 들어가는 기본 대여 기간입니다. `MAX_LOAN_DAYS`는 관리자가 기자재별로 지정할 수 있는 최대 일수입니다. 실제 기자재별 기간은 서버 실행 후 관리자 화면에서 수정합니다.

## 7-2. `best.pt`를 사용하는 경우

위 설정에서 모델 경로 한 줄만 다음처럼 바꿉니다.

> **편집 위치: Raspberry Pi의 `.env` 파일(nano 화면)**

```dotenv
YOLO_MODEL_PATH=models/best.pt
```

## 7-3. USB 카메라를 사용하는 경우

카메라 부분을 다음처럼 바꿉니다.

> **편집 위치: Raspberry Pi의 `.env` 파일(nano 화면)**

```dotenv
CAMERA_BACKEND=opencv
CAMERA_INDEX=0
```

## 7-4. 클래스 별칭 수정

아래 줄은 모델의 이름과 웹사이트의 기자재 이름을 연결합니다.

> **편집 위치: Raspberry Pi의 `.env` 파일(nano 화면)**

```dotenv
YOLO_CLASS_ALIASES='{"multimeter":"멀티미터","arduino":"아두이노","breadboard":"브레드보드"}'
```

왼쪽 이름은 YOLO를 학습할 때 `data.yaml`에 작성한 클래스 이름입니다. 오른쪽 이름은 웹 관리자 화면에 등록된 기자재 이름입니다.

예를 들어 모델 클래스가 다음과 같다면:

> **확인 위치: Google Colab 학습용 `data.yaml` 파일**

```yaml
names:
  0: meter
  1: uno
```

설정은 다음처럼 작성합니다.

> **편집 위치: Raspberry Pi의 `.env` 파일(nano 화면)**

```dotenv
YOLO_CLASS_ALIASES='{"meter":"멀티미터","uno":"아두이노"}'
```

바깥쪽 작은따옴표와 안쪽 큰따옴표를 지우지 않습니다.

## 7-5. nano에서 저장하기

수정을 완료한 뒤 다음 순서로 누릅니다.

> **입력 위치: Raspberry Pi 터미널에서 열린 nano 화면**

1. `Ctrl+O`: 저장
2. `Enter`: 파일 이름 확인
3. `Ctrl+X`: nano 종료

---

# 8부. 실제 모델과 카메라 점검하기

카메라 앞에 인식할 기자재 하나만 놓습니다. 배경을 단순하게 하고 물체 전체가 화면에 들어오게 합니다.

Pi 터미널에서 실행합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/pi_diagnostics.py
```

정상일 때는 다음과 비슷하게 출력됩니다.

```text
=== Raspberry Pi 실제 장치 사전 점검 ===
[통과] YOLO 모델 로딩
[통과] 카메라 프레임: 640x480
[통과] 현재 물체: 멀티미터 (91.2%)
전체 사전 점검 시간: 2.31초
점검 후 RSS: 430.5 MB
```

물체가 검출되지 않아도 카메라 프레임과 모델 실행이 정상이라면 다음 안내가 나올 수 있습니다.

```text
[안내] 현재 프레임에서 물체는 검출되지 않았지만 카메라와 모델 실행은 정상입니다.
```

이 경우 카메라와 프로그램 연결은 성공했지만 학습 데이터, 조명, 거리 또는 신뢰도 설정을 조정해야 합니다.

`[실패]`가 나오면 오류 문장을 복사해 [문제 해결](#문제-해결)에서 같은 내용을 찾습니다.

---

# 9부. 메모리가 계속 늘어나지 않는지 확인하기

Raspberry Pi 4B 2GB는 메모리가 적으므로 실제 모델로 반복 검사를 해야 합니다.

카메라 앞에 기자재를 놓고 먼저 50회 검사합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더, 가상환경 활성화 후)**

```bash
python scripts/memory_soak_test.py --scans 50 --interval 0.3 --max-growth-mb 120
```

마지막에 다음과 비슷하게 나오면 설정한 기준을 통과한 것입니다.

```text
최고 RSS: 470.2 MB
서비스 실행 중 마지막 RSS: 435.8 MB / 기준 대비 증가량: 5.3 MB
앞·뒤 구간 중앙값 증가량: 3.1 MB / 서비스 종료 후 RSS: 210.4 MB
통과: RSS 증가량이 설정 기준 이내입니다.
```

최종 배포 전에는 200회도 확인합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더, 가상환경 활성화 후)**

```bash
python scripts/memory_soak_test.py --scans 200 --interval 0.5 --max-growth-mb 120
```

프로그램은 모델과 카메라를 먼저 예열한 다음 기준 메모리를 측정합니다. 최초 모델 로딩에 필요한 정상적인 메모리를 누수로 잘못 계산하지 않습니다. 누수를 숨기지 않도록 서비스를 닫기 전의 마지막 RSS와 앞·뒤 측정 구간의 중앙값을 모두 비교합니다.

---

# 10부. 웹사이트 실제 실행하기

진단과 메모리 검사를 통과한 뒤 실행합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더, 가상환경 활성화 후)**

```bash
MALLOC_ARENA_MAX=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
python -m waitress --listen=0.0.0.0:8080 --threads=2 wsgi:app
```

정상 메시지:

```text
Serving on http://0.0.0.0:8080
```

다른 PC나 스마트폰 브라우저에서 엽니다.

```text
http://equipment-pi.local:8080
```

또는 Pi의 IP를 사용합니다.

```text
http://<PI_IP>:8080
```

메뉴 용도:

- `현황`: 누구나 현재 수량 확인
- `대여·반납`: 기본적으로 PIN 없이 바로 카메라 인식 화면 사용
- `관리자`: 선생님 또는 개발자 계정으로 로그인해 종류·수량·기록 관리
- `시스템`: 개발자 계정으로 로그인했을 때만 보이는 서버·DB·모델 진단

2GB Pi에서는 서버 프로세스를 여러 개 실행하지 않습니다. 현재 설정은 서버 프로세스 1개, 웹 스레드 2개, 동시 YOLO 추론 1개를 사용합니다.

---

# 11부. 전원을 켜면 자동 실행되게 만들기

수동 웹 실행을 먼저 확인하고 `Ctrl+C`로 종료합니다. 그다음 실행합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더)**

```bash
sudo bash deploy/install_service.sh
```

설치가 끝나면 상태를 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl status equipment-manager.service
```

아래 문구가 보이면 실행 중입니다.

```text
Active: active (running)
```

설치기는 테스트용 `mock` 모드가 아니라 `DETECTOR_MODE=yolo`인지, 설정한 모델 파일 또는 NCNN 폴더가 실제로 존재하는지 먼저 확인합니다. 조건이 맞지 않으면 자동 서비스를 설치하지 않고 수정할 내용을 화면에 알려줍니다.

상태 화면에서 빠져나오려면 `q`를 누릅니다.

웹 서버 로그를 실시간으로 보려면 다음을 실행합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
journalctl -u equipment-manager.service -f
```

로그 화면은 `Ctrl+C`로 종료합니다. 서비스를 설치한 뒤에는 SSH 연결을 닫아도 웹사이트가 계속 실행되고, Pi를 재부팅해도 자동으로 시작합니다.

서비스를 다시 시작하거나 멈추는 명령:

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl restart equipment-manager.service
sudo systemctl stop equipment-manager.service
sudo systemctl start equipment-manager.service
```

---

# 12부. 학교에서 실제 사용하는 순서

## 학생이 대여할 때

1. Pi 카메라 앞에 기자재 하나를 놓습니다.
2. 웹사이트에서 `대여·반납`을 누릅니다.
3. 학번을 입력합니다.
4. `대여`를 선택합니다.
5. 수량을 입력합니다.
6. `객체 인식 시작`을 누릅니다.
7. 인식된 이름과 관리자가 설정한 대여 기간·반납 예정일을 확인합니다.
8. `이 결과로 처리`를 누릅니다.
9. 현황 화면에서 사용 가능 수량이 줄었는지 확인합니다.

## 학생이 반납할 때

같은 순서에서 `반납`을 선택합니다. 해당 학번이 빌린 수량보다 많이 반납할 수는 없습니다.

반납 예정일이 오늘이면 오늘까지는 정상입니다. 예정일이 어제 이전이고 미반납 수량이 남아 있으면 연체로 바뀝니다. 연체 학생도 반납은 계속할 수 있지만 새 대여는 차단됩니다. 여러 건이 연체됐다면 연체 수량을 모두 반납해야 다시 대여할 수 있습니다.

## 관리자가 할 일

1. `관리자` 메뉴에서 로그인합니다.
2. `기자재 설정`에서 종류를 추가·수정·제거하고 실제 보유 수량과 기자재별 `대여 기간(일)`을 입력합니다. `0일`은 대여 당일이 반납 예정일이라는 뜻입니다.
3. 기간을 바꾸면 이미 진행 중인 대여의 날짜는 유지되고, 변경 후 새로 대여하는 건부터 적용됩니다.
4. 미반납 기자재가 있는 종류는 제거할 수 없습니다. 제거해도 과거 거래 기록은 남으며, 같은 이름으로 다시 추가하면 기존 종류가 재활성화됩니다.
5. 미반납 목록에서 반납 예정일과 `연체·대여 제한` 표시를 확인합니다.
6. 잘못 입력된 거래는 먼저 `취소`하여 재고를 복구합니다.
7. 취소된 거래 기록을 완전히 지워야 한다면 개발자 계정으로 로그인해 `삭제`합니다. 선생님 계정에는 삭제 버튼이 표시되지 않습니다.
8. 필요하면 CSV로 기록을 내려받습니다.

---

# 13부. 학교의 다른 장소에서 접속하기

같은 학교 안에서도 네트워크가 다음처럼 분리되어 있을 수 있습니다.

- 학생 Wi-Fi
- 교사용 Wi-Fi
- 실습실 유선망
- 게스트 Wi-Fi
- 층별 또는 교실별 VLAN

아래 장소에서 `http://<PI_IP>:8080` 접속을 하나씩 확인합니다.

1. Pi와 같은 실습실
2. 다른 교실
3. 다른 층
4. 학생 Wi-Fi 스마트폰
5. 교사용 Wi-Fi 기기
6. 유선 LAN PC

같은 실습실에서는 되지만 다른 장소에서만 안 되면 코드 문제가 아니라 학교 방화벽이나 VLAN 문제일 가능성이 큽니다.

학교 전산 담당자에게 다음을 요청합니다.

- Raspberry Pi 고정 IP 또는 DHCP 예약
- 필요한 내부망 사이의 TCP 8080 통신 허용
- 교내 Raspberry Pi 웹 서버 운영 허가

Raspberry Pi의 8080 포트를 외부 인터넷에 직접 개방하지 않습니다. 학교 밖에서도 접속해야 한다면 학교가 승인한 VPN이나 별도 중앙 서버가 필요합니다.

---

# 14부. 프로그램 업데이트와 백업

## GitHub의 새 코드 받기

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
git pull
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
python -m unittest discover -s tests -v
sudo bash deploy/install_service.sh
```

비공개 저장소 인증을 다시 요구하면 GitHub 사용자명과 Personal Access Token을 입력합니다.

## DB 백업

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/backup_db.py
```

백업 파일은 `backups` 폴더에 생깁니다. 중요한 운영 전후에는 이 폴더를 다른 PC나 USB 저장장치에도 복사합니다.

백업 명령은 `.env`에 `DATABASE` 경로를 따로 설정한 경우에도 그 DB를 찾아 백업하고, 생성된 파일이 정상 SQLite DB인지 무결성 검사까지 수행합니다. 서버가 실행 중이어도 SQLite 백업 API를 사용하므로 파일을 단순 복사하는 것보다 안전합니다.

대여 기한 기능이 포함된 버전을 처음 실행하면 기존 DB에 필요한 열과 대여 상태 표가 자동으로 추가됩니다. 기존 기자재에는 `DEFAULT_LOAN_DAYS` 값이 들어가며 관리자 화면에서 기자재별로 바꿀 수 있습니다. 기존 거래는 보존되고 예전 거래에는 반납 예정일이 없으므로 자동 연체 처리하지 않습니다. 업데이트 전 위 백업 명령을 한 번 실행하는 것을 권장합니다.

---

# 15부. 학습 사진 모으기

Pi 카메라로 학습용 원본 사진을 자동 촬영할 수 있습니다.

멀티미터를 하나만 놓고 실행합니다.

> **실행 위치: Raspberry Pi 터미널(카메라가 연결된 Pi)**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/capture_samples.py multimeter --count 250 --interval 0.5
```

다른 종류도 같은 방식으로 촬영합니다.

> **실행 위치: Raspberry Pi 터미널(같은 프로젝트 폴더와 가상환경)**

```bash
python scripts/capture_samples.py arduino --count 250 --interval 0.5
python scripts/capture_samples.py breadboard --count 250 --interval 0.5
```

사진은 다음 폴더에 저장됩니다.

```text
datasets/raw/multimeter/
datasets/raw/arduino/
datasets/raw/breadboard/
```

촬영할 때 물체의 각도, 거리, 배경, 조명을 계속 조금씩 바꿉니다. 실제 학교에서 카메라를 설치할 위치와 비슷한 사진도 포함합니다.

촬영한 사진은 라벨링한 뒤 `training/YOLO_기자재_학습_Colab.ipynb`로 학습합니다. 모델 클래스명은 영문 소문자로 단순하게 만드는 것을 권장합니다.

---

# 문제 해결

## `git clone`에서 로그인이 실패합니다

GitHub 계정 비밀번호는 Git 명령의 비밀번호로 사용할 수 없습니다. 사용자명에는 GitHub 사용자명을, 비밀번호 자리에는 저장소 읽기 권한이 있는 Personal Access Token을 입력합니다.

다음 오류는 주소가 틀렸거나 계정에 비공개 저장소 접근 권한이 없을 때도 발생합니다.

```text
Repository not found
```

저장소 주소와 로그인한 GitHub 계정을 확인합니다.

## `No module named ...` 오류가 나옵니다

프로젝트 폴더로 이동하고 가상환경을 켭니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
```

## `externally-managed-environment`가 나옵니다

가상환경이 활성화되지 않은 상태입니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
source .venv/bin/activate
```

명령줄 앞에 `(.venv)`가 생긴 뒤 다시 설치합니다.

## 카메라를 찾지 못합니다

먼저 자동 웹 서비스를 멈춥니다. 웹 서비스와 진단 프로그램이 카메라를 동시에 사용할 수 없기 때문입니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl stop equipment-manager.service
rpicam-still --output camera-test.jpg
```

그래도 실패하면 다음을 확인합니다.

- 카메라 케이블 방향
- 커넥터 잠금
- 카메라가 전원을 끈 상태에서 연결되었는지
- 다른 카메라 프로그램이 실행 중인지
- 공식 카메라인데 `.env`가 `CAMERA_BACKEND=picamera2`인지
- USB 카메라인데 `.env`가 `CAMERA_BACKEND=opencv`인지

점검 후 서비스를 다시 시작합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl start equipment-manager.service
```

## `YOLO 모델을 찾을 수 없습니다`가 나옵니다

모델과 설정을 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
cd ~/raspberry-pi-equipment-manager
ls -la models
grep YOLO_MODEL_PATH .env
```

예를 들어 실제 파일이 `models/best.pt`라면 설정도 정확히 다음이어야 합니다.

> **편집 위치: Raspberry Pi의 `.env` 파일**

```dotenv
YOLO_MODEL_PATH=models/best.pt
```

## 인식은 되지만 DB 기자재와 연결되지 않습니다

오류에 표시된 모델 클래스명과 관리자 화면의 기자재명을 확인합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더)**

```bash
grep YOLO_CLASS_ALIASES .env
```

별칭의 왼쪽은 모델 클래스명, 오른쪽은 웹사이트 기자재명입니다. 대소문자와 공백도 정확히 맞아야 합니다.

## 물체를 자주 잘못 인식합니다

다음 순서로 확인합니다.

1. 카메라 앞에 기자재를 한 종류만 놓습니다.
2. 단색 배경과 일정한 조명을 사용합니다.
3. 물체 전체가 화면 안에 들어오게 합니다.
4. 실제 설치 위치 사진을 학습 데이터에 추가합니다.
5. 오인식된 장면을 다시 촬영하고 라벨링합니다.
6. 모델을 다시 학습합니다.

무조건 신뢰도 기준만 높이면 미검출이 늘어날 수 있으므로 실제 사진으로 비교합니다.

## `Address already in use`가 나옵니다

이미 자동 서비스가 8080 포트를 사용 중일 수 있습니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl status equipment-manager.service
```

수동으로 실행하려면 서비스를 먼저 멈춥니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl stop equipment-manager.service
```

## 웹사이트가 다른 PC에서 열리지 않습니다

Pi 자체에서 먼저 확인합니다.

> **실행 위치: Raspberry Pi 터미널**

```bash
curl http://127.0.0.1:8080/healthz
hostname -I
```

`"ok":true`가 보이면 프로그램은 실행 중입니다. 같은 네트워크에서도 접속이 안 되면 IP 주소, 공유기 AP 격리, 학교 방화벽과 VLAN을 확인합니다.

## 재부팅 후 자동 실행되지 않습니다

> **실행 위치: Raspberry Pi 터미널**

```bash
sudo systemctl status equipment-manager.service
journalctl -u equipment-manager.service -n 100 --no-pager
```

출력된 마지막 오류부터 확인합니다. `.env`를 수정했다면 다시 설치해 설정을 반영합니다.

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더)**

```bash
sudo bash deploy/install_service.sh
```

## 메모리 검사에 실패합니다

> **실행 위치: Raspberry Pi 터미널(프로젝트 폴더, 가상환경 활성화 후)**

```bash
python scripts/memory_soak_test.py --scans 200 --interval 0.5
```

종료 RSS가 계속 커지면 다음 값을 순서대로 낮춰 비교합니다.

> **편집 위치: Raspberry Pi의 `.env` 파일**

```dotenv
YOLO_IMAGE_SIZE=320
YOLO_FRAME_COUNT=3
CAMERA_WIDTH=640
CAMERA_HEIGHT=480
```

서버 프로세스를 두 개 이상 실행하지 않습니다. 자동 서비스가 실행 중일 때 별도의 수동 서버를 함께 실행하지 않습니다.

---

# Windows에서 카메라 없이 기능 시험하기

Windows PowerShell에서 실행합니다.

> **실행 위치: Windows PC의 PowerShell**

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

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8080
```

Windows 기본 설정은 `mock` 모드이므로 실제 카메라가 없어도 됩니다.

---

# 기술 설명

## 메모리 사용을 줄이기 위해 적용한 내용

- YOLO 모델은 매 요청마다 만들지 않고 프로세스당 한 번만 불러옵니다.
- 카메라도 인식마다 열고 닫지 않고 한 번 연결한 뒤 재사용합니다.
- 한 번에 하나의 YOLO 추론만 실행합니다.
- 결과가 이미 확정되면 남은 프레임 추론을 생략합니다.
- Ultralytics 결과를 `stream=True`로 받고 사용 직후 스트림 참조를 해제합니다.
- Ultralytics predictor에 남는 마지막 프레임·결과 참조도 추론 직후 비웁니다.
- Picamera2 버퍼를 2개로 제한하고 오래된 프레임을 큐에 쌓지 않습니다.
- GPIO 요청마다 새 스레드를 만들지 않고 고정 worker 한 개만 사용하며, 동시 첫 요청에서도 표시기를 한 번만 생성합니다.
- 성공과 실패를 모두 포함해 일정 시도 횟수마다 Python 가비지 컬렉션을 실행합니다.
- 서버 종료 시 카메라, YOLO predictor·모델, GPIO, heartbeat의 참조를 순서대로 해제합니다.
- 반납 연결 조회와 메모리 반복 검사의 표본 저장량을 제한해 실행 횟수가 늘어도 임시 목록이 계속 커지지 않습니다.
- heartbeat와 `/healthz`에서 현재 RSS 메모리를 확인합니다.
- systemd에서 메모리 완화 기준 1300MB와 상한 1600MB를 적용합니다.

## 주요 폴더

```text
equipment_manager/
  routes/                 웹 주소와 API
  vision/camera.py        Picamera2/USB 카메라
  vision/detector.py      YOLO 인식
  vision/service.py       추론 잠금과 서비스 수명 관리
  inventory.py            대여·반납 규칙
  db.py                   SQLite DB
  hardware.py             LED와 부저
deploy/                   자동 실행 설정
scripts/                  설치·진단·백업 도구
training/                 Colab 학습 자료
tests/                    자동 테스트
```

## 웹 주소

| 주소 | 용도 |
|---|---|
| `/` | 공개 기자재 현황 |
| `/station/login` | PIN 보호를 켠 경우의 스테이션 로그인 |
| `/scan` | 객체 인식과 대여·반납 |
| `/admin/login` | 관리자 로그인 |
| `/admin` | 재고·거래·미반납 관리 |
| `/developer` | 개발자 전용 시스템 진단 |
| `/admin/export.csv` | 거래 CSV 내려받기 |
| `/api/status` | 현황과 메모리 상태 JSON |
| `/healthz` | 서버와 DB 상태 검사 |

## 자동 테스트

> **실행 위치: Windows PC 또는 Raspberry Pi의 프로젝트 폴더(가상환경 활성화 후)**

```bash
python -m compileall -q equipment_manager scripts tests wsgi.py
python -m unittest discover -s tests -v
```

자동 테스트는 임시 DB와 가짜 카메라 결과를 사용하므로 실제 운영 DB를 바꾸지 않습니다. 실제 카메라와 모델은 `pi_diagnostics.py`와 `memory_soak_test.py`로 확인합니다.

## 참고 문서

- [Raspberry Pi 처음 설치하기](https://www.raspberrypi.com/documentation/computers/getting-started.html)
- [Raspberry Pi 카메라 명령](https://www.raspberrypi.com/documentation/computers/camera_software.html)
- [Picamera2 설명서](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
- [GitHub 저장소 복제 방법](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)
- [Ultralytics Raspberry Pi 가이드](https://docs.ultralytics.com/guides/raspberry-pi/)
- [Ultralytics NCNN 안내](https://docs.ultralytics.com/integrations/ncnn/)
- [Ultralytics 예측과 stream 옵션](https://docs.ultralytics.com/modes/predict/)

---

# 최종 배포 전 체크리스트

- [ ] Pi 카메라 시험 사진이 정상이다.
- [ ] 실제 기자재로 YOLO 모델을 학습했다.
- [ ] `pi_diagnostics.py`가 통과한다.
- [ ] 인식 결과와 실제 기자재 이름이 일치한다.
- [ ] 200회 메모리 반복 검사를 통과한다.
- [ ] 실제 전체 수량을 관리자 화면에 입력했다.
- [ ] 관리자 화면에서 기자재마다 대여 기간을 정했다.
- [ ] 연체 학번의 새 대여 차단과 반납 처리를 시험했다.
- [ ] 개발자 계정과 선생님 계정의 아이디·비밀번호를 각각 기록했다.
- [ ] 스테이션 PIN 보호를 사용할지 결정했다.
- [ ] DB를 백업했다.
- [ ] 같은 교실, 다른 교실과 다른 층에서 접속을 시험했다.
- [ ] 학교 전산 담당자에게 고정 IP와 포트 사용을 확인했다.
- [ ] 재부팅 후 서비스가 자동 실행되는지 확인했다.
