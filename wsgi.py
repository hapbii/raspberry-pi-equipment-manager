"""Reject the legacy launch path that bypassed deployment/resource checks."""

raise RuntimeError(
    "실행 명령이 변경되었습니다. 프로젝트 폴더에서 python serve.py를 사용하세요. "
    "모델 없는 웹 확인만 할 때는 python serve.py --allow-mock을 사용하세요. "
    ".env와 DB는 삭제하거나 다시 생성하지 마세요."
)
