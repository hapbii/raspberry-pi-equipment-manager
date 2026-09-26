# YOLO 데이터셋 준비

라파 카메라 촬영부터 PC 전송·라벨링까지는 [메인 README 15부](../README.md#15부-사진-촬영부터-pc-복사라벨링까지)를 순서대로 따라 하세요. **라파에서는 화면 없이 엔터로 촬영하고, PC에서는 사진을 가져와 180도 회전한 다음 X-AnyLabeling으로 라벨링**합니다. `best.pt` 없이 촬영할 수 있습니다. [추가 촬영 옵션과 문제 해결](PHOTO_CAPTURE.md)도 제공합니다.

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
YOLO_CLASS_ALIASES={"raspberry_pi":"라즈베리파이","arduino":"아두이노","breadboard":"브레드보드"}
```

`YOLO_기자재_학습_Colab.ipynb`를 Google Drive에 올린 뒤 Colab에서 실행하면 학습, 검증, 테스트 이미지 추론, NCNN 변환을 순서대로 수행할 수 있습니다.

`dataset_example.yaml`을 `equipment_dataset/data.yaml`로 복사하면 됩니다. `names` 번호는 `classes.txt`의 줄 순서 및 내보낸 YOLO TXT의 번호와 반드시 같아야 합니다. 현재 예시는 라즈베리파이부터 PIR 센서까지 7종입니다. 클래스 일부만 촬영했다고 남은 항목을 삭제하거나 번호를 다시 매기지 마세요. 학습 대상을 줄이려면 라벨링 시작 전에 클래스 목록과 YAML을 함께 정해야 합니다.
