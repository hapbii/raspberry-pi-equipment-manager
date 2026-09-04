from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import current_app

from .db import get_db, utc_now


STUDENT_ID_PATTERN = re.compile(r"^[0-9A-Za-z가-힣_-]{2,30}$")


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class TransactionResult:
    transaction_id: str
    equipment_name: str
    action: str
    quantity: int
    available_qty: int
    total_qty: int


def list_inventory() -> list[dict]:
    rows = get_db().execute(
        """
        SELECT id, name, total_qty, available_qty,
               total_qty - available_qty AS loaned_qty, updated_at
        FROM equipment
        WHERE active = 1
        ORDER BY name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_equipment(equipment_id: int) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM equipment WHERE id = ? AND active = 1", (equipment_id,)
    ).fetchone()
    return dict(row) if row else None


def find_equipment_by_name(name: str) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM equipment WHERE name = ? AND active = 1", (name,)
    ).fetchone()
    return dict(row) if row else None


def add_equipment(name: str, total_qty: int) -> None:
    clean_name = name.strip()
    if len(clean_name) < 2 or len(clean_name) > 40:
        raise InventoryError("기자재 이름은 2~40자로 입력해 주세요.")
    if total_qty < 0 or total_qty > 9999:
        raise InventoryError("전체 수량은 0~9999 사이여야 합니다.")
    db = get_db()
    now = utc_now()
    try:
        db.execute(
            """
            INSERT INTO equipment(name, total_qty, available_qty, active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (clean_name, total_qty, total_qty, now, now),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise InventoryError("이미 등록된 기자재 이름입니다.") from exc


def create_scan_session(equipment_id: int, confidence: float) -> dict:
    equipment = get_equipment(equipment_id)
    if not equipment:
        raise InventoryError("등록되지 않은 기자재입니다.")

    token = uuid.uuid4().hex
    created = datetime.now(timezone.utc)
    ttl = current_app.config["SCAN_TOKEN_TTL_SECONDS"]
    expires = created + timedelta(seconds=ttl)
    db = get_db()
    db.execute("DELETE FROM scan_sessions WHERE expires_at < ?", (created.isoformat(timespec="seconds"),))
    db.execute(
        """
        INSERT INTO scan_sessions(token, equipment_id, confidence, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            token,
            equipment_id,
            max(0.0, min(1.0, confidence)),
            created.isoformat(timespec="seconds"),
            expires.isoformat(timespec="seconds"),
        ),
    )
    db.commit()
    return {
        "token": token,
        "equipment_id": equipment_id,
        "equipment_name": equipment["name"],
        "confidence": confidence,
        "expires_at": expires.isoformat(timespec="seconds"),
    }


def _validate_student_id(student_id: str) -> str:
    value = student_id.strip()
    if not STUDENT_ID_PATTERN.fullmatch(value):
        raise InventoryError("학번은 2~30자의 한글, 영문, 숫자, 밑줄 또는 하이픈만 사용할 수 있습니다.")
    return value


def _student_balance(db: sqlite3.Connection, student_id: str, equipment_id: int) -> int:
    row = db.execute(
        """
        SELECT COALESCE(SUM(CASE action WHEN 'loan' THEN quantity ELSE -quantity END), 0)
        FROM transactions
        WHERE student_id = ? AND equipment_id = ? AND reversed_at IS NULL
        """,
        (student_id, equipment_id),
    ).fetchone()
    return int(row[0])


def commit_transaction(
    scan_token: str,
    student_id: str,
    action: str,
    quantity: int,
) -> TransactionResult:
    student_id = _validate_student_id(student_id)
    if action not in {"loan", "return"}:
        raise InventoryError("대여 또는 반납을 선택해 주세요.")
    if not isinstance(quantity, int) or quantity < 1 or quantity > 20:
        raise InventoryError("수량은 1~20 사이여야 합니다.")

    db = get_db()
    now = utc_now()
    try:
        db.execute("BEGIN IMMEDIATE")
        scan = db.execute(
            """
            SELECT s.*, e.name, e.total_qty, e.available_qty
            FROM scan_sessions s
            JOIN equipment e ON e.id = s.equipment_id
            WHERE s.token = ?
            """,
            (scan_token,),
        ).fetchone()
        if not scan:
            raise InventoryError("유효하지 않은 인식 결과입니다. 다시 촬영해 주세요.")
        if scan["consumed_at"]:
            raise InventoryError("이미 처리된 인식 결과입니다.")
        if datetime.fromisoformat(scan["expires_at"]) < datetime.now(timezone.utc):
            raise InventoryError("인식 결과의 유효 시간이 지났습니다. 다시 촬영해 주세요.")

        duplicate_window = current_app.config["DUPLICATE_WINDOW_SECONDS"]
        duplicate_after = (datetime.now(timezone.utc) - timedelta(seconds=duplicate_window)).isoformat(
            timespec="seconds"
        )
        duplicate = db.execute(
            """
            SELECT 1 FROM transactions
            WHERE student_id = ? AND equipment_id = ? AND action = ?
              AND quantity = ? AND reversed_at IS NULL AND created_at >= ?
            LIMIT 1
            """,
            (student_id, scan["equipment_id"], action, quantity, duplicate_after),
        ).fetchone()
        if duplicate:
            raise InventoryError("같은 거래가 방금 처리되었습니다. 잠시 후 다시 시도해 주세요.")

        available = int(scan["available_qty"])
        total = int(scan["total_qty"])
        if action == "loan":
            if available < quantity:
                raise InventoryError("사용 가능한 수량이 부족합니다.")
            new_available = available - quantity
        else:
            balance = _student_balance(db, student_id, scan["equipment_id"])
            if balance < quantity:
                raise InventoryError("이 학생의 미반납 수량보다 많이 반납할 수 없습니다.")
            if available + quantity > total:
                raise InventoryError("반납 후 수량이 전체 수량을 초과합니다.")
            new_available = available + quantity

        transaction_id = uuid.uuid4().hex
        db.execute(
            "UPDATE equipment SET available_qty = ?, updated_at = ? WHERE id = ?",
            (new_available, now, scan["equipment_id"]),
        )
        db.execute(
            """
            INSERT INTO transactions(
                id, student_id, equipment_id, action, quantity,
                confidence, scan_token, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                student_id,
                scan["equipment_id"],
                action,
                quantity,
                scan["confidence"],
                scan_token,
                now,
            ),
        )
        db.execute("UPDATE scan_sessions SET consumed_at = ? WHERE token = ?", (now, scan_token))
        db.commit()
        return TransactionResult(
            transaction_id=transaction_id,
            equipment_name=scan["name"],
            action=action,
            quantity=quantity,
            available_qty=new_available,
            total_qty=total,
        )
    except Exception:
        db.rollback()
        raise


def list_transactions(limit: int = 100, query: str = "") -> list[dict]:
    clean_query = query.strip()[:80]
    params: list = []
    where = ""
    if clean_query:
        where = "WHERE t.student_id LIKE ? OR e.name LIKE ?"
        pattern = f"%{clean_query}%"
        params.extend([pattern, pattern])
    params.append(max(1, min(limit, 500)))
    rows = get_db().execute(
        f"""
        SELECT t.id, t.student_id, e.name AS equipment_name, t.action,
               t.quantity, t.confidence, t.created_at, t.reversed_at, t.reversed_by
        FROM transactions t
        JOIN equipment e ON e.id = t.equipment_id
        {where}
        ORDER BY t.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_outstanding() -> list[dict]:
    rows = get_db().execute(
        """
        SELECT t.student_id, e.name AS equipment_name,
               SUM(CASE t.action WHEN 'loan' THEN t.quantity ELSE -t.quantity END) AS quantity,
               MAX(t.created_at) AS last_activity
        FROM transactions t
        JOIN equipment e ON e.id = t.equipment_id
        WHERE t.reversed_at IS NULL
        GROUP BY t.student_id, t.equipment_id
        HAVING quantity > 0
        ORDER BY t.student_id, e.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def update_equipment(equipment_id: int, total_qty: int, available_qty: int) -> None:
    if total_qty < 0 or available_qty < 0 or available_qty > total_qty:
        raise InventoryError("수량은 0 이상이며, 사용 가능 수량은 전체 수량을 넘을 수 없습니다.")
    db = get_db()
    result = db.execute(
        """
        UPDATE equipment
        SET total_qty = ?, available_qty = ?, updated_at = ?
        WHERE id = ? AND active = 1
        """,
        (total_qty, available_qty, utc_now(), equipment_id),
    )
    if result.rowcount != 1:
        db.rollback()
        raise InventoryError("기자재를 찾을 수 없습니다.")
    db.commit()


def reverse_transaction(transaction_id: str, reversed_by: str = "admin") -> None:
    db = get_db()
    now = utc_now()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """
            SELECT t.*, e.total_qty, e.available_qty
            FROM transactions t
            JOIN equipment e ON e.id = t.equipment_id
            WHERE t.id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if not row:
            raise InventoryError("거래를 찾을 수 없습니다.")
        if row["reversed_at"]:
            raise InventoryError("이미 취소된 거래입니다.")

        available = int(row["available_qty"])
        if row["action"] == "loan":
            new_available = available + int(row["quantity"])
            if new_available > int(row["total_qty"]):
                raise InventoryError("취소 후 수량이 전체 수량을 초과합니다.")
        else:
            new_available = available - int(row["quantity"])
            if new_available < 0:
                raise InventoryError("취소 후 사용 가능 수량이 음수가 됩니다.")

        db.execute(
            "UPDATE equipment SET available_qty = ?, updated_at = ? WHERE id = ?",
            (new_available, now, row["equipment_id"]),
        )
        db.execute(
            "UPDATE transactions SET reversed_at = ?, reversed_by = ? WHERE id = ?",
            (now, reversed_by, transaction_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
