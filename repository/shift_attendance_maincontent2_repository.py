"""repository.shift_attendance_maincontent2_repository

Repository wrapper cho Shift Attendance - MainContent2.

Nguồn dữ liệu:
- attendance_audit: dữ liệu chấm công tổng hợp
- arrange_schedules + arrange_schedule_detail_shifts (hoặc arrange_schedule_details): lịch làm việc
- work_shifts: khai báo ca làm việc (giờ vào/ra, nghỉ trưa, total_minutes, work_count)
"""

from __future__ import annotations

from typing import Any

from core.database import Database

from repository.attendance_audit_repository import AttendanceAuditRepository


class ShiftAttendanceMainContent2Repository:
    def __init__(self, audit_repo: AttendanceAuditRepository | None = None) -> None:
        self._audit_repo = audit_repo or AttendanceAuditRepository()

    def list_audit_rows(
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
        return self._audit_repo.list_rows(
            from_date=from_date,
            to_date=to_date,
            employee_id=employee_id,
            attendance_code=attendance_code,
            employee_ids=employee_ids,
            attendance_codes=attendance_codes,
            department_id=department_id,
            title_id=title_id,
        )

    def get_schedule_id_map(self, schedule_names: list[str]) -> dict[str, int]:
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
            "SELECT id, schedule_name "
            "FROM hr_attendance.arrange_schedules "
            f"WHERE schedule_name IN ({placeholders})"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                cursor.execute(query, tuple(names))
                rows = list(cursor.fetchall() or [])
            out: dict[str, int] = {}
            for r in rows:
                try:
                    key = str(r.get("schedule_name") or "").strip()
                    if not key:
                        continue
                    out[key] = int(r.get("id"))
                except Exception:
                    continue
            return out
        finally:
            if cursor is not None:
                cursor.close()

    def get_schedule_day_shift_ids(self, schedule_id: int) -> dict[str, list[int]]:
        """Return day_key -> [shift_id...] by position.

        Prefer arrange_schedule_detail_shifts (unlimited shifts).
        If empty, fallback to arrange_schedule_details.shift1..shift5.
        """

        sid = int(schedule_id)

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)

                q1 = (
                    "SELECT day_key, shift_id "
                    "FROM hr_attendance.arrange_schedule_detail_shifts "
                    "WHERE schedule_id = %s "
                    "ORDER BY day_key ASC, position ASC"
                )
                cursor.execute(q1, (sid,))
                rows = list(cursor.fetchall() or [])

                result: dict[str, list[int]] = {}
                for r in rows:
                    dk = str(r.get("day_key") or "").strip()
                    if not dk:
                        continue
                    v = r.get("shift_id")
                    if v is None:
                        continue
                    try:
                        result.setdefault(dk, []).append(int(v))
                    except Exception:
                        continue

                if result:
                    return result

                # fallback shift1..shift5
                q2 = (
                    "SELECT day_key, shift1_id, shift2_id, shift3_id, shift4_id, shift5_id "
                    "FROM hr_attendance.arrange_schedule_details "
                    "WHERE schedule_id = %s"
                )
                cursor.execute(q2, (sid,))
                rows2 = list(cursor.fetchall() or [])
                for r in rows2:
                    dk = str(r.get("day_key") or "").strip()
                    if not dk:
                        continue
                    ids: list[int] = []
                    for k in (
                        "shift1_id",
                        "shift2_id",
                        "shift3_id",
                        "shift4_id",
                        "shift5_id",
                    ):
                        v = r.get(k)
                        if v is None:
                            continue
                        try:
                            ids.append(int(v))
                        except Exception:
                            continue
                    if ids:
                        result[dk] = ids
                return result
        finally:
            if cursor is not None:
                cursor.close()

    def get_work_shifts_by_ids(self, shift_ids: list[int]) -> dict[int, dict[str, Any]]:
        ids: list[int] = []
        for v in shift_ids or []:
            try:
                i = int(v)
            except Exception:
                continue
            if i > 0:
                ids.append(i)
        ids = sorted(set(ids))
        if not ids:
            return {}

        placeholders = ",".join(["%s"] * len(ids))
        query = (
            "SELECT id, shift_code, time_in, time_out, lunch_start, lunch_end, "
            "total_minutes, work_count, in_window_start, in_window_end, out_window_start, out_window_end, overtime_round_minutes "
            "FROM hr_attendance.work_shifts "
            f"WHERE id IN ({placeholders})"
        )

        query_legacy = (
            "SELECT id, shift_code, time_in, time_out, lunch_start, lunch_end, "
            "total_minutes, work_count "
            "FROM hr_attendance.work_shifts "
            f"WHERE id IN ({placeholders})"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                try:
                    cursor.execute(query, tuple(ids))
                except Exception as exc:
                    # Backward-compatible: older DBs may not have overtime_round_minutes yet.
                    msg = str(exc)
                    if "overtime_round_minutes" in msg and "Unknown column" in msg:
                        cursor.execute(query_legacy, tuple(ids))
                    else:
                        raise
                rows = list(cursor.fetchall() or [])

            out: dict[int, dict[str, Any]] = {}
            for r in rows:
                try:
                    row = dict(r)
                    # Ensure key exists even when legacy query was used.
                    row.setdefault("overtime_round_minutes", 0)
                    row.setdefault("in_window_start", None)
                    row.setdefault("in_window_end", None)
                    row.setdefault("out_window_start", None)
                    row.setdefault("out_window_end", None)
                    out[int(row.get("id"))] = row
                except Exception:
                    continue
            return out
        finally:
            if cursor is not None:
                cursor.close()

    def list_holiday_dates(
        self,
        *,
        from_date: str | None,
        to_date: str | None,
    ) -> set[str]:
        """Return set of holiday dates as ISO strings (yyyy-MM-dd) within range."""

        if not from_date or not to_date:
            return set()

        query = (
            "SELECT holiday_date "
            "FROM holidays "
            "WHERE holiday_date >= %s AND holiday_date <= %s"
        )

        cursor = None
        try:
            with Database.connect() as conn:
                cursor = Database.get_cursor(conn, dictionary=True)
                cursor.execute(query, (str(from_date), str(to_date)))
                rows = list(cursor.fetchall() or [])

            out: set[str] = set()
            for r in rows:
                d = r.get("holiday_date")
                try:
                    if hasattr(d, "isoformat"):
                        out.add(d.isoformat())
                    else:
                        s = str(d or "").strip()
                        if s:
                            out.add(s)
                except Exception:
                    continue
            return out
        finally:
            if cursor is not None:
                cursor.close()
