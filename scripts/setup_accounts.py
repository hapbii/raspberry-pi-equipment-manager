from __future__ import annotations

import sys
from pathlib import Path


root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from equipment_manager.account_setup import ensure_role_accounts  # noqa: E402


try:
    accounts, added = ensure_role_accounts(root / ".env")
except OSError as exc:
    raise SystemExit(str(exc)) from exc

print("계정 설정을 확인했습니다.")
print(f"개발자 아이디: {accounts['DEVELOPER_USERNAME']}")
print(f"개발자 비밀번호: {accounts['DEVELOPER_PASSWORD']}")
print(f"선생님 아이디: {accounts['TEACHER_USERNAME']}")
print(f"선생님 비밀번호: {accounts['TEACHER_PASSWORD']}")
print(f"스테이션 PIN 보호: {accounts['STATION_AUTH_REQUIRED']}")
if added:
    print(f".env에 추가한 항목: {', '.join(added)}")
    print("서버를 다시 시작해야 새 계정이 적용됩니다.")
else:
    print("이미 모든 계정 항목이 있어서 파일을 변경하지 않았습니다.")
print("비밀번호가 보이는 이 화면은 다른 사람에게 공유하지 마세요.")
