# YOLO 모델 위치

개발 중에는 이 폴더에 `best.pt`를 넣습니다.

NCNN을 사용할 때는 변환 결과 폴더 전체를 넣습니다.

```text
models/
  best.pt
  best_ncnn_model/
    model.ncnn.bin
    model.ncnn.param
    metadata.yaml
```

학습 모델은 파일 크기가 크고 다시 생성할 수 있으므로 기본 `.gitignore`에서 제외됩니다.
