"""repository.shift_attendance_maincontent2_repository

Repository SQL cho MainContent2 (Shift Attendance).

Trách nhiệm:
- Chỉ truy vấn dữ liệu từ bảng attendance_audit (và join employees để lọc theo phòng ban/chức vụ).
- Trả về dữ liệu dạng dict để UI/controller render.

Lưu ý:
- Không xử lý nghiệp vụ sắp xếp in/out ở đây (thuộc Service layer).
"""

from __future__ import annotations

import logging
from typing import Any

from core.database import Database


logger = logging.getLogger(__name__)


class ShiftAttendanceMainContent2Repository:
    TABLE = "attendance_audit"

    def update_shift_codes(self, items: list[tuple[int, str | None]]) -> int:
        """Batch update shift_code by attendance_audit.id.

        items: list of (audit_id, shift_code). shift_code=None sẽ set NULL.
        """

        cleaned: list[tuple[str | None, int]] = []
        for audit_id, code in items or []:
            try:
                aid = int(audit_id)
            except Exception:
                continue

            if code is None:
                cleaned.append((None, aid))
                continue

            c = str(code or "").strip()
            cleaned.append((c if c else None, aid))

        if not cleaned:
            return 0

        query = f"UPDATE {self.TABLE} SET shift_code = %s WHERE id = %s"

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=False)
                cursor.executemany(query, cleaned)
                try:
                    conn.commit()
                except Exception:
                    pass
                try:
                    return int(cursor.rowcount or 0)
                except Exception:
                    return 0
        except Exception:
            logger.exception("Lỗi update_shift_codes")
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def list_holiday_dates(
        self,
        *,
        from_date: str | None,
        to_date: str | None,
    ) -> set[str]:
        if not from_date or not to_date:
            return set()

        query = (
            "SELECT holiday_date FROM hr_attendance.holidays "
            "WHERE holiday_date BETWEEN %s AND %s"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                cursor.execute(query, (str(from_date), str(to_date)))
                rows = list(cursor.fetchall() or [])
                out: set[str] = set()
                for r in rows:
                    v = r.get("holiday_date")
                    if v is None:
                        continue
                    out.add(str(v))
                return out
        except Exception:
            logger.exception("Lỗi list_holiday_dates")
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def get_schedule_id_mode_by_names(
        self, schedule_names: list[str]
    ) -> dict[str, dict[str, Any]]:
        names: list[str] = []
        for n in schedule_names or []:
            s = str(n or "").strip()
            if s:
                names.append(s)
        names = list(dict.fromkeys(names))
        if not names:
            return {}

        placeholders = ",".join(["%s"] * len(names))
        query = (
            "SELECT id, schedule_name, in_out_mode "
            "FROM hr_attendance.arrange_schedules "
            f"WHERE schedule_name IN ({placeholders})"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                cursor.execute(query, tuple(names))
                rows = list(cursor.fetchall() or [])
                out: dict[str, dict[str, Any]] = {}
                for r in rows:
                    key = str(r.get("schedule_name") or "").strip()
                    if not key:
                        continue
                    out[key] = {
                        "schedule_id": r.get("id"),
                        "in_out_mode": r.get("in_out_mode"),
                    }
                return out
        except Exception:
            logger.exception("Lỗi get_schedule_id_mode_by_names")
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def get_schedule_details_by_schedule_ids(
        self, schedule_ids: list[int]
    ) -> dict[tuple[int, str], dict[str, Any]]:
        ids: list[int] = []
        for v in schedule_ids or []:
            try:
                ids.append(int(v))
            except Exception:
                continue
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}

        placeholders = ",".join(["%s"] * len(ids))
        query = (
            "SELECT schedule_id, day_key, day_name, day_order, "
            "shift1_id, shift2_id, shift3_id, shift4_id, shift5_id "
            "FROM hr_attendance.arrange_schedule_details "
            f"WHERE schedule_id IN ({placeholders})"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                cursor.execute(query, tuple(ids))
                rows = list(cursor.fetchall() or [])
                out: dict[tuple[int, str], dict[str, Any]] = {}
                for r in rows:
                    sid = r.get("schedule_id")
                    day_key = str(r.get("day_key") or "").strip()
                    if sid is None or not day_key:
                        continue
                    try:
                        out[(int(sid), day_key)] = r
                    except Exception:
                        continue
                return out
        except Exception:
            logger.exception("Lỗi get_schedule_details_by_schedule_ids")
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def get_work_shifts_by_ids(self, shift_ids: list[int]) -> dict[int, dict[str, Any]]:
        ids: list[int] = []
        for v in shift_ids or []:
            try:
                ids.append(int(v))
            except Exception:
                continue
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}

        placeholders = ",".join(["%s"] * len(ids))
        query = (
            "SELECT id, shift_code, time_in, time_out, lunch_start, lunch_end, "
            "total_minutes, work_count, in_window_start, in_window_end, "
            "out_window_start, out_window_end, overtime_round_minutes "
            "FROM hr_attendance.work_shifts "
            f"WHERE id IN ({placeholders})"
        )
        query_legacy = (
            "SELECT id, shift_code, time_in, time_out, lunch_start, lunch_end, "
            "total_minutes, work_count, in_window_start, in_window_end, "
            "out_window_start, out_window_end "
            "FROM hr_attendance.work_shifts "
            f"WHERE id IN ({placeholders})"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                try:
                    cursor.execute(query, tuple(ids))
                    rows = list(cursor.fetchall() or [])
                except Exception as exc:
                    msg = str(exc)
                    if "overtime_round_minutes" in msg and "Unknown column" in msg:
                        cursor.execute(query_legacy, tuple(ids))
                        rows = list(cursor.fetchall() or [])
                        for r in rows:
                            try:
                                r.setdefault("overtime_round_minutes", 0)
                            except Exception:
                                pass
                    else:
                        raise

                out: dict[int, dict[str, Any]] = {}
                for r in rows:
                    sid = r.get("id")
                    if sid is None:
                        continue
                    try:
                        out[int(sid)] = r
                    except Exception:
                        continue
                return out
        except Exception:
            logger.exception("Lỗi get_work_shifts_by_ids")
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def list_rows(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        employee_id: int | None = None,
        attendance_code: str | None = None,
        employee_ids: list[int] | None = None,
        attendance_codes: list[str] | None = None,
        department_id: int | None = None,
        title_id: int | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []

        if from_date:
            where.append("a.work_date >= %s")
            params.append(str(from_date))
        if to_date:
            where.append("a.work_date <= %s")
            params.append(str(to_date))

        ac = str(attendance_code or "").strip()

        ids: list[int] = []
        for v in employee_ids or []:
            try:
                ids.append(int(v))
            except Exception:
                continue
        codes: list[str] = [str(s or "").strip() for s in (attendance_codes or [])]
        codes = [s for s in codes if s]

        if employee_id is not None:
            ids.append(int(employee_id))
        if ac:
            codes.append(ac)

        ids = list(dict.fromkeys(ids))
        codes = list(dict.fromkeys(codes))

        if ids or codes:
            parts: list[str] = []
            if ids:
                parts.append("a.employee_id IN (" + ",".join(["%s"] * len(ids)) + ")")
                params.extend(ids)
            if codes:
                parts.append(
                    "a.attendance_code IN (" + ",".join(["%s"] * len(codes)) + ")"
                )
                params.extend(codes)
            if parts:
                where.append("(" + " OR ".join(parts) + ")")

        join_sql = (
            " LEFT JOIN hr_attendance.employees e "
            "   ON (e.id = a.employee_id OR e.mcc_code = a.attendance_code OR e.employee_code = a.attendance_code) "
        )
        if department_id is not None:
            where.append("e.department_id = %s")
            params.append(int(department_id))
        if title_id is not None:
            where.append("e.title_id = %s")
            params.append(int(title_id))

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        query = (
            "SELECT "
            "a.id, "
            "a.attendance_code, a.employee_code, a.full_name, a.work_date AS date, a.weekday, "
            "a.in_1, a.out_1, a.in_2, a.out_2, a.in_3, a.out_3, "
            "a.late, a.early, a.hours, a.work, a.`leave`, a.`leave` AS kh, a.hours_plus, a.work_plus, a.leave_plus, "
            "CASE "
            "  WHEN a.work IS NULL AND a.work_plus IS NULL THEN NULL "
            "  ELSE (COALESCE(a.work, 0) + COALESCE(a.work_plus, 0)) "
            "END AS total, "
            "a.tc1, a.tc2, a.tc3, "
            "a.shift_code AS shift_code_db, "
            "COALESCE(("
            "  SELECT s.schedule_name "
            "  FROM hr_attendance.employee_schedule_assignments esa "
            "  JOIN hr_attendance.arrange_schedules s ON s.id = esa.schedule_id "
            "  WHERE esa.employee_id = e.id "
            "    AND esa.effective_from <= a.work_date "
            "    AND (esa.effective_to IS NULL OR esa.effective_to >= a.work_date) "
            "  ORDER BY esa.effective_from DESC, esa.id DESC "
            "  LIMIT 1"
            "), a.schedule) AS schedule "
            f"FROM {self.TABLE} a"
            f"{join_sql}"
            f"{where_sql} "
            "ORDER BY a.work_date ASC, a.employee_code ASC, a.id ASC"
        )

        query_legacy = (
            "SELECT "
            "a.id, "
            "a.attendance_code, a.employee_code, a.full_name, a.work_date AS date, a.weekday, "
            "a.in_1, a.out_1, a.in_2, a.out_2, a.in_3, a.out_3, "
            "a.late, a.early, a.hours, a.work, a.`leave`, a.`leave` AS kh, a.hours_plus, a.work_plus, a.leave_plus, "
            "CASE "
            "  WHEN a.work IS NULL AND a.work_plus IS NULL THEN NULL "
            "  ELSE (COALESCE(a.work, 0) + COALESCE(a.work_plus, 0)) "
            "END AS total, "
            "a.tc1, a.tc2, a.tc3, "
            "COALESCE(("
            "  SELECT s.schedule_name "
            "  FROM hr_attendance.employee_schedule_assignments esa "
            "  JOIN hr_attendance.arrange_schedules s ON s.id = esa.schedule_id "
            "  WHERE esa.employee_id = e.id "
            "    AND esa.effective_from <= a.work_date "
            "    AND (esa.effective_to IS NULL OR esa.effective_to >= a.work_date) "
            "  ORDER BY esa.effective_from DESC, esa.id DESC "
            "  LIMIT 1"
            "), a.schedule) AS schedule "
            f"FROM {self.TABLE} a"
            f"{join_sql}"
            f"{where_sql} "
            "ORDER BY a.work_date ASC, a.employee_code ASC, a.id ASC"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                try:
                    cursor.execute(query, tuple(params))
                except Exception as exc:
                    msg = str(exc)
                    if "shift_code" in msg and "Unknown column" in msg:
                        cursor.execute(query_legacy, tuple(params))
                    else:
                        raise

                rows = list(cursor.fetchall() or [])
                for r in rows:
                    r.setdefault("shift_code_db", None)
                return rows
        except Exception:
            logger.exception("Lỗi list_rows (shift_attendance_maincontent2)")
            raise
        finally:
            if cursor is not None:
                cursor.close()
