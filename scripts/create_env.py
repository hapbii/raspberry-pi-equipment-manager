from __future__ import annotations

import secrets
from pathlib import Path


root = Path(__file__).resolve().parent.parent
template_path = root / ".env.example"
output_path = root / ".env"

if output_path.exists():
    raise SystemExit(
        f"이미 .env 파일이 있습니다: {output_path}\n"
        "역할별 계정만 추가하려면 python scripts/setup_accounts.py 를 실행하세요."
    )

developer_password = secrets.token_urlsafe(12)
developer_username = "developer"
teacher_password = secrets.token_urlsafe(12)
teacher_username = "teacher"
station_pin = f"{secrets.randbelow(1_000_000):06d}"
secret_key = secrets.token_hex(32)

lines = []
for line in template_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("SECRET_KEY="):
        line = f"SECRET_KEY={secret_key}"
    elif line.startswith("DEVELOPER_USERNAME="):
        line = f"DEVELOPER_USERNAME={developer_username}"
    elif line.startswith("DEVELOPER_PASSWORD="):
        line = f"DEVELOPER_PASSWORD={developer_password}"
    elif line.startswith("TEACHER_USERNAME="):
        line = f"TEACHER_USERNAME={teacher_username}"
    elif line.startswith("TEACHER_PASSWORD="):
        line = f"TEACHER_PASSWORD={teacher_password}"
    elif line.startswith("STATION_PIN="):
        line = f"STATION_PIN={station_pin}"
    lines.append(line)

output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
output_path.chmod(0o600)

print(f"생성 완료: {output_path}")
print(f"개발자 아이디: {developer_username}")
print(f"개발자 비밀번호: {developer_password}")
print(f"선생님 아이디: {teacher_username}")
print(f"선생님 비밀번호: {teacher_password}")
print(f"스테이션 PIN(보호 기능을 켤 때만 사용): {station_pin}")
print("이 값은 다시 자동 표시되지 않으므로 안전한 곳에 기록하세요.")
