# best.pt와 NCNN 비교

2026-10-04에 같은 YOLO11n 모델을 두 형식으로 비교했습니다. 원본 `best.pt`는 보존하고 NCNN을 추가 생성했습니다. 이 작업은 운영 모델을 교체하거나 서비스를 재시작하지 않습니다.

## 파일 위치

로컬 워크스페이스 기준:

```text
output/equipment_training_20261002_134412/
  equipment6_20261003_093310/weights/best.pt  # Colab 학습 원본
  equipment_dataset/                       # 학습 433장, 검증 109장
  ncnn_comparison_20261004_320/
    best.pt                                # 원본과 SHA256이 같은 사본
    best_ncnn_model/                        # 입력 320으로 변환한 NCNN
    export_report.json                     # 원본 보존·클래스 순서·파일 해시
    pc-results-runtime2/                   # PC에서 완료한 비교
    pi-results-runtime2/                   # 실제 Pi 4에서 완료한 비교
```

모델과 사진은 `.gitignore`에 따라 로컬에 보관합니다. NCNN 실행에는 `model.ncnn.bin`, `model.ncnn.param`, `metadata.yaml`이 필요합니다. `.pt`처럼 파일 하나만 복사하지 말고 모델 폴더를 복사하세요. `model_ncnn.py`는 내보내기 과정에서 생성되는 사용 예제입니다.

## 변환 다시 실행하기 — PC

별도 Python 환경에 변환 도구를 설치합니다. 현재 비교에 사용한 Ultralytics는 8.4.164입니다.

```powershell
python -m venv tmp/model-tools
.\tmp\model-tools\Scripts\python.exe -m pip install torch torchvision ultralytics==8.4.164 ncnn==1.0.20260526 pnnx==20260526
.\tmp\model-tools\Scripts\python.exe scripts/export_ncnn.py output/equipment_training_20261002_134412/equipment6_20261003_093310/weights/best.pt --output-dir output/equipment_training_20261002_134412/ncnn-new-320 --imgsz 320
```

출력 폴더는 새 이름을 사용하세요. 도구는 기존 모델을 덮어쓰지 않으며, 원본을 복사한 뒤 임시 영문 경로에서 변환해 한글 Windows 경로의 TorchScript 문제를 피합니다. 변환 후 원본과 사본의 SHA256, 클래스 순서를 확인하고 보고서를 저장합니다. 현재 변환은 `quantize=32`로 FP32 가중치를 보존합니다. PT 체크포인트는 FP16으로 저장돼 있어 NCNN 파일 용량이 더 큽니다. 파일 용량과 실행 메모리는 별도로 비교해야 합니다.

입력 크기 416을 시험하려면 다른 출력 폴더와 `--imgsz 416`으로 다시 내보내세요. NCNN은 내보낸 입력 크기와 시험·운영 입력 크기를 맞춥니다.

## 비교 실행하기

도구는 카메라 대신 저장된 검증 사진을 사용합니다. 데이터 폴더에는 `images/val/*.jpg`, 대응하는 `labels/val/*.txt`, `classes.txt`가 있어야 합니다. 현재 도구는 각 사진에 물체 하나가 라벨링된 데이터셋을 대상으로 합니다.

PC PowerShell:

```powershell
.\tmp\model-tools\Scripts\python.exe scripts/compare_model_formats.py --pt output/equipment_training_20261002_134412/ncnn_comparison_20261004_320/best.pt --ncnn output/equipment_training_20261002_134412/ncnn_comparison_20261004_320/best_ncnn_model --dataset output/equipment_training_20261002_134412/equipment_dataset --output output/equipment_training_20261002_134412/ncnn-comparison-new-pc --imgsz 320 --threads 2 --conf 0.60 --repeats 2
```

라파에서는 홈 디렉토리의 별도 시험 폴더 `/home/pi30304/equipment-model-comparison-20261004`를 사용했습니다. 학습 모델 사본·NCNN 폴더·검증 사진·라벨·비교 스크립트를 SSH/SFTP로 전송했고 사진과 모델의 SHA256을 확인했습니다. 운영 프로젝트의 `.env`, 모델과 가상환경을 수정하지 않았습니다.

Pi 4의 기존 패키지 조합(Torch 2.14.0+cu130·NumPy 2.4.6·OpenCV 5.0.0.93)은 모델 로딩 후 실제 추론에서 `SIGILL`로 종료됐습니다. 실패한 개별 연산이나 패키지는 특정하지 않았습니다. 테스트 가상환경에만 Torch 2.3.1·torchvision 0.18.1·NumPy 1.26.4·OpenCV 4.11.0.86을 설치해 비교했습니다. 이 조합은 이번 모델의 실제 추론으로 검증했습니다. Pi 4의 일부 PyTorch 빌드 호환성 문제는 [Ultralytics 이슈](https://github.com/ultralytics/ultralytics/issues/15835)와 [PyTorch 이슈](https://github.com/pytorch/pytorch/issues/176993)에도 보고돼 있습니다. NCNN을 Ultralytics로 실행하는 경로 역시 Torch를 가져오므로 NCNN 모델로 바꿔도 호환되는 Python 환경은 필요합니다.

라파 SSH 터미널에서 이미 준비된 테스트 환경으로 재측정하려면:

```bash
cd /home/pi30304/equipment-model-comparison-20261004
nice -n 10 .venv/bin/python compare_model_formats.py --pt best.pt --ncnn best_ncnn_model --dataset dataset --output results-new --imgsz 320 --threads 2 --conf 0.60 --repeats 2
```

결과 폴더에는 `비교결과.md`, `comparison.json`, 개별 모델 JSON, `predictions.csv`가 저장됩니다. 기존 결과를 보존하도록 새 출력 폴더를 사용합니다.

## 측정 조건과 해석

- Raspberry Pi 4 Model B Rev 1.2, RAM 약 2GB, aarch64, Python 3.11.2에서 측정합니다. 기존 `equipment-manager` 서비스는 실행 상태를 유지합니다.
- 같은 검증 사진 109장을 같은 순서로 섞어 각 모델에서 2회, 총 218회 추론합니다. 예열 4회는 속도 통계에서 제외합니다.
- 두 모델 모두 CPU, 입력 320×320, 신뢰도 0.60, IoU 0.7, 최대 검출 5개, 배치 1을 사용합니다. `rect=False`로 PT도 정사각형 입력을 사용해 NCNN과 맞춥니다.
- Torch 스레드와 NCNN 네이티브 스레드를 각각 2로 설정합니다. NCNN은 모델을 읽기 전에 설정해야 하며, Torch 스레드 설정만으로 제한되지 않습니다.
- 속도는 전처리·추론·후처리를 포함한 `predict()` 시간입니다. 사진 읽기·카메라 촬영·웹 요청·여러 프레임 투표 시간은 포함하지 않습니다.
- 메모리는 별도 추론 프로세스의 RSS입니다. Python·Ultralytics·Torch를 포함하며 웹 서버 전체의 메모리를 뜻하지 않습니다. 50ms 간격의 관측 최대값은 정확한 할당 최대값과 다를 수 있습니다.
- PT 다음 NCNN 순서로 실행합니다. 온도·다른 서비스의 CPU 사용량 때문에 수치가 달라질 수 있습니다. CPU 사용률은 코어 하나를 100%로 계산합니다.
- 품목 정답은 신뢰도 기준을 통과한 최고 후보와 라벨 클래스를 비교합니다. 박스 정답은 품목도 맞고 IoU≥0.5인 경우입니다. 이 비율은 학습 보고서의 mAP와 다른 지표입니다.
- 이전 이름의 결과 폴더는 스레드 설정 수정 전 결과 또는 실패한 시도입니다. 위 파일 목록의 완료된 결과만 사용합니다.

## 실제 측정 결과

**측정 직후 `vcgencmd get_throttled`가 `0x50005`를 반환했습니다.** 현재 저전압·성능 제한과 과거 발생 플래그가 함께 설정된 상태입니다. [Raspberry Pi 공식 비트 설명](https://www.raspberrypi.com/documentation/computers/os.html#get_throttled)에 따른 해석이며, 시험 내내 같은 상태였는지는 기록하지 않았습니다. 아래 수치는 현재 전원 환경에서 관측한 결과입니다. 정상 전원에서의 절대 속도나 두 형식의 속도 비율로 일반화하지 마세요. 전원 어댑터·케이블 상태를 확인한 뒤 재측정해야 합니다.

Raspberry Pi 4 RAM 약 2GB에서 측정한 결과입니다. 입력 320·신뢰도 0.60이며 각 모델의 Torch 실제 스레드 값 2, NCNN 네이티브 스레드 값 2를 확인했습니다.

| 항목 | best.pt | NCNN |
|---|---:|---:|
| 추론 중앙값 | 839.91 ms | 272.20 ms |
| 추론 평균 | 836.74 ms | 272.63 ms |
| 95백분위 추론 시간 | 848.62 ms | 275.48 ms |
| 예열 후 RSS | 435.98 MiB | 440.25 MiB |
| 관측 최대 RSS | 442.10 MiB | 443.55 MiB |
| 모델 준비 | 1305.84 ms | 453.77 ms |
| 첫 추론 | 8829.89 ms | 7862.70 ms |
| 프로세스 CPU 사용률 | 190.11 % | 193.50 % |
| 모델 파일 용량 | 5.19 MiB | 9.90 MiB |
| 품목 정답 | 98/109 | 98/109 |
| 품목+박스 정답 | 98/109 | 98/109 |
| 검출 없음 | 11/109 | 11/109 |

중앙값 기준 PT 시간 / NCNN 시간은 **3.09**입니다. 같은 최고 후보 품목이 달라진 사진은 **0장**입니다. 최고 후보 신뢰도의 최대 차이는 0.00000119입니다.

관측 온도는 PT 41.4→41.9°C(최대 43.3°C), NCNN 40.4→41.9°C(최대 43.8°C)입니다.

품목별 검증 결과:

| 품목 | best.pt 정답 | NCNN 정답 |
|---|---:|---:|
| breadborad | 29/29 | 29/29 |
| wheel | 14/14 | 14/14 |
| motor | 11/20 | 11/20 |
| pirsensor | 16/18 | 16/18 |
| bimsensor | 14/14 | 14/14 |
| raspberrypi | 14/14 | 14/14 |

PC에서도 같은 사진과 조건으로 측정했습니다. PC 결과를 라파의 속도로 해석하지 마세요.

| PC 항목 | best.pt | NCNN |
|---|---:|---:|
| 추론 중앙값 | 102.55 ms | 67.62 ms |
| 예열 후 RSS | 367.76 MiB | 363.06 MiB |
| 품목 정답 | 98/109 | 98/109 |

두 형식의 인식 결과가 같은 경우 속도와 실제 메모리 사용량을 기준으로 선택할 수 있습니다. 현재 결과는 신뢰도 기준으로 걸러진 사진을 포함하며, 416 입력으로 평가한 학습 mAP50 0.995와 직접 비교하지 않습니다. 모터와 PIR의 누락 여부를 새 촬영 사진으로 확인해야 합니다.

## 운영에 적용하기 전

현재 전원 환경에서 NCNN의 추론 중앙값은 약 272ms, PT는 약 840ms로 NCNN이 약 3.09배 빨랐습니다. 인식 결과는 같았으므로 라파 실행용 후보로 NCNN을 권합니다. 원본 PT는 재학습·다른 형식 변환용으로 보관합니다. 다만 NCNN의 예열 후 RSS는 약 440MiB, PT는 약 436MiB로 **이번 실행 경로에서는 메모리 절약이 확인되지 않았습니다.** NCNN 파일도 약 9.90MiB로 PT 약 5.19MiB보다 큽니다. 선택 이유는 관측한 추론 속도이며, 정상 전원과 실제 카메라 조건에서 재확인해야 합니다.

두 형식 중 선택한 뒤 [메인 README의 모델 적용 절차](../README.md#model)를 따릅니다. NCNN이면 `YOLO_MODEL_PATH=models/best_ncnn_model`, `YOLO_IMAGE_SIZE=320`으로 맞춥니다. 이번 비교는 모델 선택을 위한 시험이며 운영 설정을 변경하지 않았습니다.

앱은 이제 모델 준비가 끝난 뒤 `INFERENCE_THREADS`를 Torch에 재적용합니다. NCNN은 해당 모델의 네트워크를 지정 스레드 수로 로딩하고 초기 네트워크를 해제한 뒤 재사용합니다. 다른 모델이나 전역 `ncnn.Net`을 변경하지 않습니다. 비교 도구도 Torch·NCNN의 실제 값이 2인지 확인합니다. 앱의 PT 기본 입력은 직사각형 최적화를 사용할 수 있어 이번 정사각형 비교와 처리 시간이 다를 수 있습니다. 실제 카메라·웹 화면에서 품목별 인식, 여러 프레임 투표와 메모리 유지 여부를 확인하세요.

새로운 날짜·조명·배경의 사진은 아직 시험하지 않았습니다. 현재 320 입력·신뢰도 0.60에서 누락되는 품목이 있으므로 입력 크기·신뢰도와 새 사진 성능을 확인한 뒤 운영 기준을 정하세요. 형식 변환 자체가 낮은 신뢰도를 해결하지는 않습니다.
