"""ui.controllers.shift_attendance_maincontent2_controllers

Controller (logic, không dựng UI) cho Shift Attendance - MainContent2:
- Load rows từ DB (attendance_audit)
- Enrich: tính hours/work + điền ký hiệu KV/KR

File này được dùng bởi ShiftAttendanceController để giữ code gọn.
"""

from __future__ import annotations

from typing import Any

from repository.shift_attendance_maincontent2_repository import (
    ShiftAttendanceMainContent2Repository,
)
from services.shift_attendance_maincontent2_services import (
    ShiftAttendanceMainContent2Service,
)


class ShiftAttendanceMainContent2Controller:
    def __init__(
        self,
        *,
        repository: ShiftAttendanceMainContent2Repository | None = None,
        service: ShiftAttendanceMainContent2Service | None = None,
    ) -> None:
        self._repo = repository or ShiftAttendanceMainContent2Repository()
        self._service = service or ShiftAttendanceMainContent2Service()

    def list_rows_enriched(
        self,
        *,
        from_date: str | None,
        to_date: str | None,
        employee_ids: list[int] | None,
        attendance_codes: list[str] | None,
        department_id: int | None,
        title_id: int | None,
    ) -> list[dict[str, Any]]:
        rows = self._repo.list_audit_rows(
            from_date=from_date,
            to_date=to_date,
            employee_ids=employee_ids,
            attendance_codes=attendance_codes,
            department_id=department_id,
            title_id=title_id,
        )

        # Build schedule->shift context for correct hours/work calculation.
        schedule_names: list[str] = []
        for r in rows or []:
            s = str((r or {}).get("schedule") or "").strip()
            if s:
                schedule_names.append(s)
        schedule_names = list(dict.fromkeys(schedule_names))

        schedule_id_by_name = self._repo.get_schedule_id_map(schedule_names)

        day_shift_ids_by_schedule_id: dict[int, dict[str, list[int]]] = {}
        all_shift_ids: list[int] = []
        for _name, sid in (schedule_id_by_name or {}).items():
            try:
                day_map = self._repo.get_schedule_day_shift_ids(int(sid))
            except Exception:
                day_map = {}
            day_shift_ids_by_schedule_id[int(sid)] = dict(day_map or {})
            for ids in (day_map or {}).values():
                for x in ids or []:
                    try:
                        all_shift_ids.append(int(x))
                    except Exception:
                        continue

        all_shift_ids = sorted(set([int(x) for x in all_shift_ids if int(x) > 0]))
        work_shift_by_id = self._repo.get_work_shifts_by_ids(all_shift_ids)

        holiday_dates = self._repo.list_holiday_dates(
            from_date=from_date, to_date=to_date
        )

        return self._service.enrich_rows(
            rows,
            schedule_id_by_name=schedule_id_by_name,
            day_shift_ids_by_schedule_id=day_shift_ids_by_schedule_id,
            work_shift_by_id=work_shift_by_id,
            holiday_dates=holiday_dates,
        )
