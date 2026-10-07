# YOLO 데이터셋 준비

PC에 준비한 사진을 **LabelImg의 YOLO 모드로 라벨링**합니다. 현재 카메라는 하드웨어로 방향을 수정했으므로 원본 방향을 유지합니다. 이미 라벨링한 사진을 나중에 회전하면 박스 좌표가 맞지 않습니다.

## 현재 데이터셋과 학습 결과 — 2026-10-04

로컬 `20261002_yolofile`에 사진 542장과 같은 이름의 YOLO TXT 542개가 있습니다. 기존 수동 라벨 196개를 유지하고 346개를 추가했으며, 추가 박스를 시각 검토하고 전체 라벨의 LabelImg 읽기를 확인했습니다. `motor`는 기존 라벨처럼 전선을 포함합니다. 사진과 짝이 없는 기존 TXT 복사본 13개는 보존했으며, 학습 준비 시에는 JPG와 같은 이름의 TXT만 사용하세요.

클래스 순서는 아래와 같습니다. `breadborad` 등의 철자도 기존 `classes.txt`와 일치하도록 그대로 사용합니다.

```text
0 breadborad
1 wheel
2 motor
3 pirsensor
4 bimsensor
5 raspberrypi
```

이번 데이터에는 [dataset_current_6class.yaml](dataset_current_6class.yaml)을 `equipment_dataset/data.yaml`로 복사해 사용합니다. YAML의 `path`는 실제 Colab 데이터셋 위치에 맞추세요. 기존 `dataset_example.yaml`과 `training/classes.txt`는 다른 순서의 7종 예시이므로 이번 라벨에 그대로 적용하면 클래스가 잘못 연결됩니다.

Colab T4에서 YOLO11n 학습을 완료했습니다. 촬영 시각이 가까운 같은 품목의 사진을 묶어 학습 433장·검증 109장으로 분리했습니다. 최대 80 epoch·patience 15 설정에서 46 epoch까지 실행됐고, 최적 모델은 epoch 31입니다. 학습 시간은 약 240초이며 설치·업로드 시간은 제외합니다. 입력 416에서 검증 mAP50 0.995, mAP50–95 0.8601을 기록했습니다.

원본 모델은 로컬 `output/equipment_training_20261002_134412/equipment6_20261003_093310/weights/best.pt`에 있습니다. NCNN 사본과 비교 결과는 `output/equipment_training_20261002_134412/ncnn_comparison_20261004_320/`에 보관합니다. [PT·NCNN 비교 안내](MODEL_COMPARISON.md)에 변환 방법·측정 조건·결과를 정리합니다. 사진·라벨·모델·학습 결과는 GitHub에 포함하지 않습니다.

검증 사진은 같은 장소·날짜에서 촬영됐으며 독립적인 시험 세트는 아직 없습니다. 새 사진 시험, 품목 별칭 확인과 운영 프로그램에 모델 적용이 남아 있습니다. 새 기자재를 추가해 재학습할 때는 기존 품목 사진도 함께 사용해 이전 품목의 성능을 확인하세요.

권장 폴더 구조:

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

각 이미지와 라벨 파일 이름은 같아야 합니다.

```text
images/train/photo_001.jpg
labels/train/photo_001.txt
```

처음에는 기자재 3종으로 시작하고 각 종류당 200~500장 정도를 목표로 합니다. 같은 동영상의 연속 프레임을 train과 val에 나누어 넣으면 실제보다 성능이 높게 측정되므로, 촬영 영상이나 촬영 날짜 단위로 분리하세요.

모델 클래스명은 영문으로 학습하고 서버에서 한글 이름으로 연결하는 방법이 편리합니다.

```text
YOLO_CLASS_ALIASES='{"breadborad":"브레드보드","wheel":"바퀴","motor":"서보 모터","pirsensor":"PIR 센서","bimsensor":"초음파 센서","raspberrypi":"라즈베리파이"}'
```

`YOLO_기자재_학습_Colab.ipynb`를 Google Drive에 올린 뒤 Colab에서 실행하면 학습, 검증, 테스트 이미지 추론, NCNN 변환을 순서대로 수행할 수 있습니다.

위 별칭의 오른쪽 이름은 관리자 화면에 등록된 실제 기자재 이름과 정확히 같아야 합니다. 모델 학습 후 적용 시에 설정하며, 기자재 등록과 수량 입력은 별도로 진행합니다.

`names` 번호는 데이터셋의 `classes.txt` 줄 순서 및 YOLO TXT의 번호와 반드시 같아야 합니다. 클래스 목록을 바꾸려면 모든 관련 라벨의 번호도 함께 변환해야 합니다. 이번 데이터는 위의 6종 설정을 사용하고, 7종 예시가 필요한 별도 데이터에는 `dataset_example.yaml`을 사용하세요.
