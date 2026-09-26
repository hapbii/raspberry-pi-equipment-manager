# 🐧 Linux 우분투(Ubuntu) 환경 YOLO 객체인식 완벽 가이드

본 문서는 우분투(Ubuntu Linux) 환경에서 **YOLOv8**을 설치하고, 사진/동영상/웹캠을 활용해 객체인식을 수행하는 전체 과정을 정리한 가이드입니다.

---

## 1. 사전 필수 시스템 패키지 설치

우분투 터미널에서 파이썬 가상환경(`python3-venv`)과 영상 처리 및 컴퓨터 비전 라이브러리(`OpenCV`, `GLib`)를 설치합니다.

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libgl1 libglib2.0-0
```

---

## 2. 가상환경 생성 및 Ultralytics(YOLO) 설치

시스템 기본 파이썬 패키지와의 충돌을 방지하기 위해 가상환경을 생성하고 활성화합니다.

```bash
# 1. 작업 디렉토리 생성 및 이동 (선택)
mkdir -p ~/yolo_workspace && cd ~/yolo_workspace

# 2. 가상환경 생성 및 활성화
python3 -m venv yolo_env
source yolo_env/bin/activate

# 3. 최신 pip 업데이트 및 ultralytics 설치
pip install --upgrade pip
pip install ultralytics
```

> **설치 확인**: 터미널에 `yolo version`을 입력하여 버전 정보가 정상 출력되는지 확인합니다.

---

## 3. 터미널 명령줄(CLI)로 즉시 객체인식 실행

별도의 파이썬 코드를 작성하지 않고도 터미널 명령어 한 줄로 테스트할 수 있습니다.

### ① 웹 이미지 또는 로컬 사진 인식
```bash
# 웹 샘플 이미지로 테스트
yolo predict model=yolov8n.pt source='https://ultralytics.com/images/bus.jpg'

# 내 로컬 사진으로 테스트
yolo predict model=yolov8n.pt source='test_image.jpg'
```
* **결과 저장 위치**: `runs/detect/predict/` 폴더에 바운딩 박스와 클래스명이 그려진 결과 이미지가 자동 저장됩니다.

### ② 동영상 파일 인식
```bash
yolo predict model=yolov8n.pt source='test_video.mp4' save=True
```

### ③ 웹캠/카메라 실시간 인식
```bash
# source=0 은 첫 번째 연결된 웹캠 장치(/dev/video0)를 의미
yolo predict model=yolov8n.pt source=0 show=True
```
* 웹캠 화면이 팝업 창으로 뜨며 실시간 객체인식이 시작됩니다. (종료: 키보드 `q` 키)

---

## 4. 파이썬(Python) 코드로 객체인식 제어

웹 서비스 연동, 데이터베이스 저장, 센서 제어 등 실제 프로젝트에 적용할 때는 파이썬 스크립트로 좌표와 신뢰도를 추출하여 처리합니다.

### 📄 단일 이미지 인식 스크립트 (`detect_image.py`)

```python
from ultralytics import YOLO

# 1. 사전 학습된 nano 모델 로드 (또는 직접 학습한 'best.pt')
model = YOLO("yolov8n.pt")

# 2. 이미지 객체인식 실행
# save=True: 결과 이미지를 runs/detect/ 폴더에 자동 저장
# conf=0.5: 신뢰도 50% 이상인 결과만 필터링
results = model.predict(
    source="https://ultralytics.com/images/bus.jpg",
    save=True,
    conf=0.5
)

# 3. 감지된 객체 정보 파싱
for result in results:
    boxes = result.boxes
    for box in boxes:
        cls_id = int(box.cls[0])           # 클래스 ID
        label = model.names[cls_id]         # 클래스명 (예: person, bus)
        confidence = float(box.conf[0])     # 신뢰도 (0.0 ~ 1.0)
        x1, y1, x2, y2 = box.xyxy[0].tolist() # 바운딩 박스 좌표

        print(f"[감지] 물체: {label:<10} | 정확도: {confidence * 100:.1f}% | 위치: ({x1:.0f}, {y1:.0f}) ~ ({x2:.0f}, {y2:.0f})")
```

### 📄 웹캠/CSI 카메라 실시간 스트리밍 스크립트 (`detect_webcam.py`)

```python
import cv2
from ultralytics import YOLO

# 1. 모델 로드
model = YOLO("yolov8n.pt")

# 2. 카메라 열기 (0번 카메라)
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("카메라를 열 수 없습니다.")
    exit()

print("객체 인식을 시작합니다. (종료: q 키)")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 스트림 프레임 추론
    results = model.predict(frame, conf=0.5, verbose=False)

    # 인식 결과가 시각화된 프레임 가져오기
    annotated_frame = results[0].plot()

    # 화면에 표시
    cv2.imshow("YOLOv8 Ubuntu Realtime", annotated_frame)

    # 'q' 키 누르면 종료
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

---

## 5. 우분투 환경 사용 시 주의사항 및 팁

1. **SSH 원격 접속 / 모니터 없는 환경 (Headless / Server)**:
   - GUI 창을 띄우는 `show=True`나 `cv2.imshow()`를 실행하면 `cannot connect to X server` 에러가 발생합니다.
   - 원격 환경에서는 항상 **`save=True`** 옵션을 주어 파일로 저장한 뒤 확인하거나, 웹 서버(Flask 등)로 스트리밍해야 합니다.

2. **사용자 정의 모델 사용**:
   - Roboflow 및 Google Colab에서 직접 학습시킨 커스텀 가중치 파일이 있다면:
     ```python
     model = YOLO("models/best.pt")
     ```
     경로만 변경하여 동일하게 사용하시면 됩니다.

3. **ARM CPU (라즈베리파이 등) 최적화**:
   - 우분투가 설치된 라즈베리파이 등 저사양 환경에서는 PyTorch 원본(`.pt`) 대신 **NCNN 포맷**으로 변환하여 사용하면 추론 속도가 2~3배 빨라집니다:
     ```python
     model.export(format="ncnn", imgsz=320)
     ncnn_model = YOLO("best_ncnn_model")
     ```
