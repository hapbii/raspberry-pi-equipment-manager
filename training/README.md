# YOLO 데이터셋 준비

라파 카메라로 촬영해서 PC의 labelImg에서 작업하려면 [촬영·PC 복사·labelImg 상세 안내](PHOTO_CAPTURE.md)를 먼저 보세요. `best.pt` 없이 사진을 촬영할 수 있습니다. `--preview`로 PC 브라우저에서 실시간 화면을 보며 촬영할 수 있고, SSH 연결 방법은 안내서 1~3부에 있습니다.

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
YOLO_CLASS_ALIASES={"multimeter":"멀티미터","arduino":"아두이노","breadboard":"브레드보드"}
```

`YOLO_기자재_학습_Colab.ipynb`를 Google Drive에 올린 뒤 Colab에서 실행하면 학습, 검증, 테스트 이미지 추론, NCNN 변환을 순서대로 수행할 수 있습니다.
