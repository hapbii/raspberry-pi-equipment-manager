"""Bounded, atomic equipment edits with stale-screen protection."""
from __future__ import annotations

from .db import get_db, utc_now
from .inventory import InventoryError, _deactivate_equipment, _validate_loan_period_days


FIELDS = ("total_qty", "available_qty", "loan_period_days", "updated_at")
MAX_BATCH = 100


def _integer(value, low=0, high=9999):
    if type(value) is not int or not low <= value <= high:
        raise InventoryError(f"수량과 번호는 {low}~{high} 사이의 정수로 입력해 주세요.")
    return value


def change_selected_equipment(action: str, items) -> list[dict]:
    if not isinstance(action, str) or action not in {"update", "remove"}:
        raise InventoryError("수정 또는 삭제 작업을 선택해 주세요.")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise InventoryError(f"기자재를 1~{MAX_BATCH}개 선택해 주세요.")
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise InventoryError("기자재 요청 형식이 올바르지 않습니다.")
        item_id = _integer(item.get("id"), 1, 2**63 - 1)
        if item_id in ids:
            raise InventoryError("같은 기자재를 중복 선택할 수 없습니다.")
        ids.add(item_id)
        expected = item.get("expected")
        if not isinstance(expected, dict) or any(key not in expected for key in FIELDS):
            raise InventoryError("기존 값이 누락됐습니다. 화면을 새로 열어 주세요.")
        if action == "update":
            total = _integer(item.get("total_qty"))
            available = _integer(item.get("available_qty"))
            if available > total:
                raise InventoryError("사용 가능 수량은 전체 수량을 넘을 수 없습니다.")
            _validate_loan_period_days(_integer(item.get("loan_period_days"), 0, 2**31 - 1))

    db = get_db()
    result = []
    try:
        db.execute("BEGIN IMMEDIATE")
        now = utc_now()
        for item in items:
            row = db.execute("SELECT * FROM equipment WHERE id = ? AND active = 1", (item["id"],)).fetchone()
            if row is None:
                raise InventoryError("선택한 기자재 중 이미 삭제된 항목이 있습니다. 아무 항목도 변경하지 않았습니다.")
            if any(item["expected"][key] != row[key] for key in FIELDS):
                raise InventoryError(f"{row['name']}: 대여·반납 또는 다른 관리자의 수정으로 값이 바뀌었습니다. 입력값을 따로 기록한 뒤 새로고침해 확인하세요. 아무 항목도 변경하지 않았습니다.")
            if action == "remove":
                _deactivate_equipment(db, item["id"], now)
            else:
                db.execute("""UPDATE equipment SET total_qty = ?, available_qty = ?,
                           loan_period_days = ?, updated_at = ? WHERE id = ?""",
                           (item["total_qty"], item["available_qty"], item["loan_period_days"], now, item["id"]))
            result.append(dict(db.execute("SELECT * FROM equipment WHERE id = ?", (item["id"],)).fetchone()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result
