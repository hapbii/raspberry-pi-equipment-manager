# 라파 카메라 촬영 → 180도 회전·PC 복사 → X-AnyLabeling 라벨링

`best.pt` 없이 촬영할 수 있습니다. 카메라와 같은 조명·거리·촬영 위치에서 모은 사진은 실제 사용 환경을 반영하는 데 도움이 됩니다. 한 각도에서 비슷한 사진만 수백 장 찍지 말고 각도·거리·배경을 바꾸세요.

사진은 `datasets/raw/클래스명/촬영회차/`에 저장됩니다. 회차 폴더는 실행마다 새로 생성하므로 재촬영해도 이전 사진을 덮어쓰지 않습니다. 사진과 운영 DB·비밀번호는 GitHub에 올리지 않습니다.

## 1. 라파에 접속하고 서버를 잠시 멈추기

**실행 위치: Windows PC PowerShell**

```powershell
ssh pi30304@10.177.156.96
```

비밀번호는 화면에 표시되지 않아도 입력됩니다. 다음부터 `exit` 전까지는 **라파에서 실행하는 명령**입니다. IP가 바뀌면 라파에서 `hostname -I`로 확인하세요.

이 안내의 기본 방식은 **실시간 화면 없이 엔터로 촬영**하는 것입니다. 브라우저나 SSH 터널은 필요하지 않습니다. 처음부터 PC 전송·라벨링까지 따라 하려면 [메인 README 15부](../README.md#15부-사진-촬영부터-pc-복사라벨링까지)를 보세요.

**실행 위치: 라파 SSH 터미널**

```bash
cd /home/pi30304/raspberry-pi-equipment-manager
sudo systemctl stop equipment-manager.service
source .venv/bin/activate
```

촬영 중에는 서버가 카메라를 사용하지 않도록 멈춥니다. 사이트는 촬영을 마치고 다시 켤 때까지 접속되지 않습니다. 다른 터미널에서 수동 서버를 실행했다면 그 터미널에서도 Ctrl+C로 종료하세요. 모델·DB·`.env`는 삭제하거나 새로 만들지 마세요.

## 2. 먼저 사진 한 장 시험하기

현재 서버와 동일하게 `.env`의 카메라 설정과 해상도를 사용합니다. Pi 리본 케이블 카메라는 보통 `picamera2`, USB 카메라는 `opencv`입니다.

**실행 위치: 라파 SSH 터미널 — Pi 카메라 설정 그대로 한 장 촬영**

```bash
python scripts/capture_samples.py camera_check --count 1
```

USB 카메라라면 다음 명령을 **대신** 사용합니다. 이 옵션은 이번 촬영에만 적용되며 `.env`를 변경하지 않습니다.

**실행 위치: 라파 SSH 터미널 — USB 카메라 0번**

```bash
python scripts/capture_samples.py camera_check --count 1 --backend opencv --camera-index 0
```

`camera_check` 사진은 시험용이며 학습 클래스에 포함하지 않습니다. 아래 PC 복사 명령으로 가져와 초점·밝기·색상부터 확인하세요. 본 촬영은 아래 3부의 엔터 촬영을 사용하세요.

## 3. 화면 없이 엔터로 촬영하기 (기본 방식)

**실행 위치: 라파 SSH 터미널 — 라즈베리파이 최대 200장**

```bash
python scripts/capture_samples.py raspberry_pi --manual --count 200
```

1. 촬영 영역에 라즈베리파이 기자재를 놓습니다.
2. 엔터를 누르면 기본 1초 뒤 사진을 저장합니다. 손을 치울 시간이 더 필요하면 명령 끝에 `--delay 3`을 붙이세요.
3. 각도나 위치를 바꾸고 다시 엔터를 누릅니다.
4. `q`를 입력한 뒤 엔터를 누르면 종료합니다. 200장을 전부 찍을 필요는 없습니다.
5. Ctrl+C로 중단해도 이미 저장된 사진은 유지됩니다.

USB 카메라라면 각 촬영 명령 끝에 `--backend opencv --camera-index 0`을 붙이세요. 계속 사용할 카메라 종류가 정해지면 나중에 실제 인식용 `.env`도 같은 카메라로 설정해야 합니다.

**실행 위치: 라파 SSH 터미널 — 아두이노**

```bash
python scripts/capture_samples.py arduino --manual --count 200
```

**실행 위치: 라파 SSH 터미널 — 브레드보드**

```bash
python scripts/capture_samples.py breadboard --manual --count 200
```

다른 기자재는 명령의 클래스명만 바꾸세요. 준비된 `training/classes.txt`의 순서는 `raspberry_pi`, `arduino`, `breadboard`, `wheel`, `ultrasonic_sensor`, `servo_motor`, `pir_sensor`입니다. 필요한 클래스 목록은 **라벨링을 시작하기 전에** 정하고, 시작한 뒤에는 순서를 바꾸지 마세요.

## 4. 일정 간격으로 자동 촬영하기

**실행 위치: 라파 SSH 터미널 — 3초 준비 후 2초 간격으로 100장**

```bash
python scripts/capture_samples.py raspberry_pi --count 100 --interval 2
```

같은 물체를 계속 움직이며 찍되 손에 가려지거나 흔들린 사진은 PC에서 제외하세요. 완전히 같은 장면의 연속 사진만 모으면 실제 인식 성능이 좋아지지 않을 수 있습니다.

## 5. 사진을 180도 회전해서 PC로 복사하기

촬영을 Ctrl+C로 마친 뒤, SSH 창은 그대로 두고 **PC에서 새 PowerShell 창**을 여세요. 다음은 라파에서 실행하는 명령이 아닙니다. PC의 이 프로젝트 폴더에서 실행합니다.

**실행 위치: Windows PC의 새 PowerShell — 최초 한 번만 준비**

```powershell
python -m pip install -r requirements-photo-transfer.txt
```

**실행 위치: Windows PC의 새 PowerShell — 사진 가져올 때마다 실행**

```powershell
python scripts/download_photos.py --host 10.177.156.96
```

SSH 비밀번호를 입력하고 엔터를 누릅니다. 입력한 비밀번호는 화면에 표시되거나 파일에 저장되지 않습니다. 기존 SSH 창과 별개로 전송용 SSH/SFTP 연결을 열며, 8081 미리보기 터널은 필요하지 않습니다. IP가 바뀌면 `--host` 뒤 주소만 바꾸세요.

처음 접속하는 주소라면 먼저 PC에서 `ssh pi30304@10.177.156.96`으로 정상 접속해 장치를 확인하세요. 도구는 PC의 `.ssh/known_hosts`에 등록된 장치만 사용하며, 키가 다르면 연결을 중단합니다.

- **결과 위치:** 실행 시 표시되는 `사용자 홈/Downloads/equipment-photos-날짜시간-식별자/raw/기자재명/촬영회차/`.
- **회전 방향:** 상하 반전이나 거울 반사가 아닌 **180도 회전**입니다. 거꾸로 설치된 카메라 사진을 바로 세웁니다.
- **처리 위치:** 라파 사진을 PC의 임시 파일로 한 장씩 받은 뒤, PC에서 회전해 최종 폴더에 저장합니다. 라파 원본·촬영 프로그램·미리보기는 그대로이고 라파에 새 패키지를 설치하지 않습니다.
- **복사 대상:** JPG/JPEG/PNG 사진과 `training/classes.txt`. 기자재·회차 폴더와 사진 이름을 유지합니다. `camera_check` 시험 사진도 포함되지만 학습에서는 제외하세요.
- **라벨링 전 전용:** 기존 TXT/JSON 라벨은 복사하지 않습니다. 회전하면 좌표가 달라지므로 **완성된 PC 사진으로 새로 라벨링**하세요.
- **사진 품질:** JPG는 품질 95로 다시 저장하므로 재압축됩니다. 크기와 색상 순서는 유지하고, EXIF 방향을 픽셀에 반영한 뒤 방향 태그를 제거해 프로그램마다 다시 뒤집히지 않도록 합니다.
- **재실행:** 매번 라파 원본에서 새 폴더로 가져옵니다. 이미 회전한 PC 파일을 다시 회전하거나 기존 라벨을 덮어쓰지 않습니다. 같은 사진을 다시 받으면 별도 복사본이 생깁니다.
- **중단:** 완성된 사진은 남고, 받던 사진·임시 파일은 정리합니다. `transfer.json`의 `status`가 `complete`이면 전체 완료, `incomplete`이면 일부만 완료된 상태입니다. 재개가 필요하면 명령을 다시 실행해 새 폴더로 전체 복사하세요.

**실행 위치: Windows PC PowerShell — 라즈베리파이 사진만 가져오는 선택 예시**

```powershell
python scripts/download_photos.py --host 10.177.156.96 --class-name raspberry_pi
```

**실행 위치: Windows PC PowerShell — 저장할 새 폴더를 지정하는 선택 예시**

```powershell
python scripts/download_photos.py --host 10.177.156.96 --output "$env:USERPROFILE\Downloads\labeling-photos-01"
```

워크스페이스 안으로 가져오려면 다음 명령을 **대신** 사용하세요.

**실행 위치: Windows PC PowerShell — 프로젝트 폴더**

```powershell
$captureFolder = Join-Path (Get-Location).Path ("datasets\labeling-photos-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
python scripts/download_photos.py --host 10.177.156.96 --output "$captureFolder"
```

`datasets`는 GitHub 업로드에서 제외됩니다. PC에서 프로젝트 폴더를 여는 방법과 패키지 준비는 [README 15-3](../README.md#15-3-가져오기-코드를-실행할-pc-준비하기)을 참고하세요.

지정한 폴더가 이미 존재하면 중단합니다. 새 이름을 쓰세요. 기본 라파 프로젝트 경로는 `/home/pi30304/raspberry-pi-equipment-manager`입니다. 다른 사용자·경로라면 `--user 사용자명 --remote-project /절대/프로젝트/경로`를 지정하세요. 나중에 카메라 방향을 고쳐 회전이 필요 없어지면 `--rotation 0`을 붙입니다.

학습 사진은 이제 바로 선 방향이고, 현재 실제 인식 코드의 카메라 입력은 여전히 거꾸로입니다. `best.pt` 적용 때에는 인식 입력도 같은 방향으로 보정하거나, 뒤집힌 방향을 포함한 학습·검증을 해야 합니다. 이 전송 도구는 실제 대여·반납의 카메라 입력을 변경하지 않습니다.

## 6. X-AnyLabeling에서 YOLO 라벨 만들기

PC의 **X-AnyLabeling 4.0.6**으로 회전된 사진을 엽니다. 박스 그리기, 클래스별 번호, 일반 JSON 저장과 YOLO TXT 내보내기의 차이, 내보낸 파일 확인 방법은 [README 15-5~15-7](../README.md#15-5-x-anylabeling에서-박스-그리기)에 자세히 정리했습니다. 그 순서대로 진행하세요. 시험용 `camera_check`는 학습에서 제외합니다.

YOLO TXT 한 줄은 `클래스번호 중심X 중심Y 너비 높이`이며 좌표·크기는 0~1로 정규화됩니다. `classes.txt` 첫 줄이 0번입니다. **폴더마다 클래스 순서가 달라지면 다른 물체로 학습되므로 모든 촬영회차에서 같은 목록을 사용하세요.** 클래스 목록에서 안 보이는 이름을 즉석에서 추가하기보다 원래 목록과 일치하는지 먼저 확인하세요.

사진만으로 `best.pt`가 생성되지는 않습니다. 라벨링 뒤에는 기존 Colab 안내서대로 데이터 분리 → `data.yaml` 작성 → 학습을 해야 합니다. 같은 촬영회차 사진을 train/val/test에 무작위로 흩뿌리지 말고 회차 단위로 나누는 것이 좋습니다. `camera_check` 시험 사진은 제외하세요.

## 7. 촬영을 마치고 사이트 다시 켜기

**실행 위치: 라파 SSH 터미널**

```bash
sudo systemctl start equipment-manager.service
systemctl is-active equipment-manager.service
```

`active`가 뜨면 PC에서 `http://10.177.156.96:8080`으로 확인하세요. 촬영은 모델 없이 가능하지만 실제 대여·반납 객체 인식은 `best.pt` 적용 후 별도 점검이 필요합니다.

## 선택 기능: 실시간 미리보기

기본 엔터 촬영에는 필요 없는 선택 기능입니다. 미리보기를 사용할 때만 일반 SSH 연결 대신 아래 연결을 사용합니다. 터미널을 닫지 마세요.

**실행 위치: Windows PC PowerShell — 선택 기능용 SSH 터널**

```powershell
ssh -o ExitOnForwardFailure=yes -L 127.0.0.1:8081:127.0.0.1:8081 pi30304@10.177.156.96
```

접속 후 프로젝트 폴더로 이동하고, 대여 서버를 멈추고 가상환경을 활성화하는 단계는 1부와 같습니다.

**실행 위치: 라파 SSH 터미널 — 라즈베리파이 최대 200장, 실시간 미리보기**

```bash
python scripts/capture_samples.py raspberry_pi --preview --count 200
```

**접속 위치: Windows PC 브라우저 주소창 — 명령어가 아니라 사이트 주소입니다**

```text
http://127.0.0.1:8081
```

1. 카메라의 실시간 화면이 PC 브라우저에 나타납니다. 이 주소에서는 기자재 대여 사이트가 아니라 **촬영 전용 화면**이 열립니다. 선생님·개발자 로그인이 필요하지 않으며 SSH 접속으로 보호됩니다.
2. 촬영하려는 기자재를 화면에 맞추고 손을 치웁니다. **사진 촬영** 버튼을 한 번 누르면 새 사진 한 장을 라파에 저장합니다. 화면을 보고 있는 것만으로 사진이 저장되지는 않습니다.
3. `저장 완료` 메시지와 저장 장수가 올라갔는지 확인합니다. 각도·거리·배경을 바꾸며 반복하세요. 저장 도중에는 중복 클릭되지 않습니다.
4. 미리보기는 라파 2GB 메모리와 통신량을 고려해 **가로 최대 640px, 초당 최대 약 5회**로 갱신합니다. 실제 속도는 카메라·네트워크에 따라 더 느릴 수 있습니다. 저장 사진은 `.env`에 설정한 **카메라 원본 해상도**입니다. 화면의 글씨나 버튼은 사진에 찍히지 않습니다.
5. 다른 브라우저 탭을 보거나 창을 최소화하면 미리보기 요청이 멈추고 표시하던 이미지 메모리를 정리합니다. 돌아오면 새 화면과 저장 장수를 다시 읽습니다. 전송 전 대기 중인 촬영 클릭은 취소되며, 이미 전송된 저장은 완료될 수 있지만 자동 재촬영하지 않습니다. `--count 200`은 저장 가능한 최대 장수이며 200장을 모두 찍을 필요는 없습니다. 최대 장수에 도달하면 촬영 버튼만 잠깁니다.
6. 끝나면 **라파 SSH 터미널에서 Ctrl+C**를 누릅니다. 브라우저만 닫으면 프로그램과 카메라는 계속 열려 있습니다. 저장한 사진은 남습니다.
7. 다음 기자재 촬영 명령을 실행한 뒤 PC 브라우저를 **새로고침(F5)** 하세요. 프로그램을 다시 실행하면 보안 토큰도 바뀌므로 새로고침이 필요합니다.

**실행 위치: 라파 SSH 터미널 — 아두이노 실시간 촬영**

```bash
python scripts/capture_samples.py arduino --preview --count 200
```

**실행 위치: 라파 SSH 터미널 — 브레드보드 실시간 촬영**

```bash
python scripts/capture_samples.py breadboard --preview --count 200
```

USB 카메라라면 위 명령 끝에 `--backend opencv --camera-index 0`을 붙이세요. 미리보기 촬영은 버튼 방식이며 `--manual`과 함께 쓸 수 없습니다. `--delay`, `--interval`은 미리보기 버튼 촬영에는 적용되지 않습니다.

카메라 화면은 학교 Wi-Fi 전체에 공개하지 않고 **라파 내부 주소에만** 엽니다. 따라서 PC에서 `http://라파IP:8081`로 직접 접속하는 것은 의도적으로 안 됩니다. 꼭 SSH 터널과 `http://127.0.0.1:8081`을 사용하세요. 사진은 PC 브라우저 다운로드 폴더가 아니라 **라파의 `datasets/raw/클래스명/촬영회차/`**에 저장됩니다. PC 복사는 5부를 따라 하세요.


## 문제 해결

- 미리보기 페이지가 안 열림: PC에서 `-L`이 포함된 SSH로 접속했는지, 라파에서 `--preview` 촬영 명령이 실행 중인지 확인하세요. 주소는 `https`가 아닌 `http://127.0.0.1:8081`입니다.
- `Address already in use` / `cannot listen to port`: 이전 미리보기 프로그램이나 SSH 창을 닫은 뒤 다시 실행하세요. 다른 작업의 프로세스를 무작정 종료하지 마세요. 8081이 다른 용도로 사용 중이면 아래 별도 포트 예시를 사용하세요.
- 페이지는 보이지만 화면 오류: 라파 터미널의 카메라 오류를 확인하세요. 프로그램을 재실행한 뒤에는 브라우저 F5도 눌러 주세요.
- `Camera frontend has timed out` / `카메라가 5초 동안 영상을 보내지 않았습니다`: 카메라 이름이 검색되어도 영상이 들어오지 않는 상태일 수 있습니다. 촬영 프로그램을 Ctrl+C로 종료하고 라파를 안전하게 종료한 뒤 전원을 분리하고 카메라 케이블·커넥터를 확인하세요. 전원이 켜진 채 리본 케이블을 빼거나 꽂지 마세요. 코드에서는 대기 중인 촬영 작업을 취소해 무한 대기를 방지합니다.
- 촬영 중 연결이 끊김: 사진이 이미 저장되었을 수 있어 자동 재촬영하지 않습니다. 다시 접속한 뒤 저장 장수와 라파 폴더를 먼저 확인하세요.
- 카메라 사용 중 오류: 서버나 다른 촬영 프로그램이 카메라를 열고 있는지 확인합니다.
- Pi 카메라를 찾지 못함: 전원을 끈 뒤 리본 케이블 방향·연결을 확인합니다. USB 카메라는 `--backend opencv`로 실행합니다.
- USB 번호 오류: `--camera-index 0`이 실제 USB 카메라 번호인지 확인합니다. `/dev/video*`에는 촬영용이 아닌 장치도 있습니다.
- 저장 실패: 디스크 여유 공간과 출력 폴더 쓰기 권한을 확인합니다. 사진은 원본을 PC로 복사·확인한 뒤 정리하세요.
- PC 복사 실패: 같은 네트워크인지, 라파 IP가 바뀌지 않았는지 확인합니다.
- 예전에 Pi 카메라로 저장한 사진 색상이 뒤집혀 있다면: 구버전 저장 코드가 원인일 수 있습니다. 새 사진과 비교하고 이상한 사진은 그대로 섞어 학습하지 마세요.

### 8081 포트가 다른 작업에 사용 중이라면

**실행 위치: Windows PC 새 PowerShell — 8082로 SSH 터널 접속**

```powershell
ssh -o ExitOnForwardFailure=yes -L 127.0.0.1:8082:127.0.0.1:8082 pi30304@10.177.156.96
```

**실행 위치: 위 명령으로 접속한 라파 SSH 터미널**

```bash
cd /home/pi30304/raspberry-pi-equipment-manager
source .venv/bin/activate
python scripts/capture_samples.py raspberry_pi --preview --preview-port 8082 --count 200
```

기자재 서버를 중지한 상태에서 실행하세요. PC 브라우저 주소도 `http://127.0.0.1:8082`로 바꿉니다.

### `numpy.dtype size changed` 오류

2026-09-23 점검한 라파에서는 가상환경 NumPy 2.4.6과 시스템 simplejpeg 1.8.1이 충돌했습니다. 시스템 패키지는 삭제하지 않고 가상환경에 simplejpeg 1.9.0을 설치한 뒤 Picamera2 가져오기와 카메라 목록 조회가 통과했습니다. 같은 simplejpeg 오류일 때만 다음 명령을 사용하세요. 다른 라이브러리에서 발생하는 오류까지 해결하는 명령은 아닙니다.

**실행 위치: 라파 SSH 터미널 — 프로젝트 폴더**

```bash
.venv/bin/python -m pip install --only-binary=:all: --no-deps simplejpeg==1.9.0
```

공식 참고: [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling), [Picamera2의 RGB888/BGR 바이트 배열](https://github.com/raspberrypi/picamera2/blob/main/picamera2/request.py).
