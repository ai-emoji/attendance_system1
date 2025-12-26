"""services.shift_attendance_maincontent2_services

Service cho MainContent2 (Shift Attendance).

Nghiệp vụ:
- Lấy dữ liệu attendance_audit.
- Tra cứu in_out_mode từ arrange_schedules theo schedule_name.
- Chuẩn hoá/sắp xếp các cột giờ vào/ra theo mode:
  - auto: sắp xếp giờ tăng dần rồi ghép (in_1/out_1/in_2/out_2/in_3/out_3).
  - device: giữ nguyên dữ liệu như audit (theo máy chấm công).
  - first_last: lấy giờ đầu tiên trong ngày làm in_1 và giờ cuối cùng làm out_1, xoá các cặp còn lại.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from repository.arrange_schedule_repository import ArrangeScheduleRepository
from repository.shift_attendance_maincontent2_repository import (
    ShiftAttendanceMainContent2Repository,
)


logger = logging.getLogger(__name__)


class ShiftAttendanceMainContent2Service:
    def __init__(
        self,
        repo: ShiftAttendanceMainContent2Repository | None = None,
        arrange_repo: ArrangeScheduleRepository | None = None,
    ) -> None:
        self._repo = repo or ShiftAttendanceMainContent2Repository()
        self._arrange_repo = arrange_repo or ArrangeScheduleRepository()

    @staticmethod
    def _time_to_seconds(value: object | None) -> int | None:
        if value is None:
            return None

        if isinstance(value, _dt.time):
            return int(value.hour) * 3600 + int(value.minute) * 60 + int(value.second)

        if isinstance(value, _dt.timedelta):
            try:
                sec = int(value.total_seconds())
                return sec % 86400
            except Exception:
                return None

        # Some drivers may return datetime or string
        if isinstance(value, _dt.datetime):
            t = value.time()
            return int(t.hour) * 3600 + int(t.minute) * 60 + int(t.second)

        s = str(value).strip()
        if not s:
            return None

        # datetime-like: keep last token
        if " " in s and ":" in s:
            s = s.split()[-1].strip()

        # Accept HH:MM or HH:MM:SS
        parts = [p for p in s.split(":") if p != ""]
        if len(parts) < 2:
            return None
        try:
            hh = int(float(parts[0]))
            mm = int(float(parts[1]))
            ss = int(float(parts[2])) if len(parts) >= 3 else 0
            if hh < 0 or mm < 0 or ss < 0:
                return None
            return hh * 3600 + mm * 60 + ss
        except Exception:
            return None

    @classmethod
    def _collect_sorted_times(cls, row: dict[str, Any]) -> list[object]:
        keys = ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3")
        items: list[tuple[int, int, object]] = []
        for idx, k in enumerate(keys):
            v = row.get(k)
            sec = cls._time_to_seconds(v)
            if sec is None:
                continue
            items.append((int(sec), int(idx), v))
        items.sort(key=lambda t: (t[0], t[1]))
        return [v for _sec, _idx, v in items]

    @staticmethod
    def _date_to_day_key(value: object | None) -> str:
        """Map date -> day_key used by arrange_schedule_details."""

        if value is None:
            return ""

        if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
            w = int(value.weekday())
        else:
            # Accept 'YYYY-MM-DD' or datetime
            try:
                if isinstance(value, _dt.datetime):
                    w = int(value.date().weekday())
                else:
                    w = int(_dt.date.fromisoformat(str(value)).weekday())
            except Exception:
                return ""

        return (
            "mon"
            if w == 0
            else (
                "tue"
                if w == 1
                else (
                    "wed"
                    if w == 2
                    else (
                        "thu"
                        if w == 3
                        else ("fri" if w == 4 else ("sat" if w == 5 else "sun"))
                    )
                )
            )
        )

    @classmethod
    def _pick_time_in_range(
        cls,
        values: list[object],
        *,
        start_sec: int | None,
        end_sec: int | None,
        pick: str,
    ) -> object | None:
        if not values:
            return None

        def _sec_in_range(s: int, start: int | None, end: int | None) -> bool:
            if start is None and end is None:
                return True
            if start is None:
                return s <= int(end)
            if end is None:
                return s >= int(start)

            # Support range that crosses midnight: e.g. 22:00 -> 02:00
            if int(start) <= int(end):
                return int(start) <= s <= int(end)
            return s >= int(start) or s <= int(end)

        def _in_range(v: object) -> bool:
            s = cls._time_to_seconds(v)
            if s is None:
                return False
            return _sec_in_range(int(s), start_sec, end_sec)

        candidates = [v for v in values if _in_range(v)]
        if not candidates:
            return None

        candidates_sorted = sorted(
            candidates,
            key=lambda v: (int(cls._time_to_seconds(v) or 0),),
        )
        return candidates_sorted[0] if pick == "first" else candidates_sorted[-1]

    @classmethod
    def _remove_first_occurrence(cls, values: list[object], target: object) -> None:
        try:
            values.remove(target)
        except Exception:
            # fallback by seconds compare
            t_sec = cls._time_to_seconds(target)
            if t_sec is None:
                return
            for i, v in enumerate(list(values)):
                if cls._time_to_seconds(v) == t_sec:
                    try:
                        values.pop(i)
                    except Exception:
                        pass
                    return

    @classmethod
    def _apply_mode_auto_by_shifts(
        cls,
        row: dict[str, Any],
        *,
        shifts: list[dict[str, Any]],
    ) -> None:
        """Auto mode dựa trên danh sách ca (work_shifts) theo thứ tự."""

        punches = cls._collect_sorted_times(row)
        keys = ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3")
        for k in keys:
            row[k] = None

        used_any = False
        used_night = False

        def _is_overnight_shift(sh: dict[str, Any]) -> bool:
            tin = cls._time_to_seconds(sh.get("time_in"))
            tout = cls._time_to_seconds(sh.get("time_out"))
            if tin is not None and tout is not None and int(tout) < int(tin):
                return True

            win_in = cls._time_to_seconds(sh.get("in_window_start"))
            win_out = cls._time_to_seconds(sh.get("out_window_end"))
            if (
                win_in is not None
                and win_out is not None
                and int(win_out) < int(win_in)
            ):
                return True

            return False

        def _pick_out_relaxed(
            values: list[object],
            *,
            shift: dict[str, Any],
            out_start_sec: int | None,
            out_end_sec: int | None,
        ) -> object | None:
            """Chọn giờ ra để HIỂN THỊ (cho phép ngoài out_window_end => tăng ca).

            Quy tắc:
            - Ca ngày: lấy lần chấm MUỘN NHẤT từ out_window_start trở đi.
            - Ca đêm: chỉ lấy giờ buổi sáng (mặc định tới 15:00) để không ăn nhầm punch buổi tối.
            """

            if not values:
                return None

            start = int(out_start_sec) if out_start_sec is not None else None

            is_night = _is_overnight_shift(shift)
            if not is_night:
                # Day shift: allow any time >= start
                candidates: list[object] = []
                for v in values:
                    s = cls._time_to_seconds(v)
                    if s is None:
                        continue
                    if start is not None and int(s) < int(start):
                        continue
                    candidates.append(v)
                if not candidates:
                    return None
                return max(candidates, key=lambda v: int(cls._time_to_seconds(v) or 0))

            # Night shift: out should be morning; allow overtime but cap by 15:00
            upper = 15 * 3600
            if out_end_sec is not None:
                try:
                    upper = max(int(upper), int(out_end_sec))
                except Exception:
                    pass
            if start is None:
                start = 0

            candidates2: list[object] = []
            for v in values:
                s = cls._time_to_seconds(v)
                if s is None:
                    continue
                if int(s) < int(start):
                    continue
                if int(s) > int(upper):
                    continue
                candidates2.append(v)
            if not candidates2:
                return None
            return max(candidates2, key=lambda v: int(cls._time_to_seconds(v) or 0))

        def _sec(v: object | None) -> int | None:
            return cls._time_to_seconds(v)

        pair_idx = 0
        for sh in shifts:
            if pair_idx >= 3:
                break

            in_start = sh.get("in_window_start") or sh.get("time_in")
            in_end = sh.get("in_window_end") or sh.get("time_in")
            out_start = sh.get("out_window_start") or sh.get("time_out")
            out_end = sh.get("out_window_end") or sh.get("time_out")

            in_start_sec = _sec(in_start)
            in_end_sec = _sec(in_end)
            out_start_sec = _sec(out_start)
            out_end_sec = _sec(out_end)

            # Strict match để XÁC ĐỊNH ca
            in_strict = None
            if in_start_sec is not None or in_end_sec is not None:
                in_strict = cls._pick_time_in_range(
                    punches,
                    start_sec=in_start_sec,
                    end_sec=in_end_sec,
                    pick="first",
                )

            out_strict = None
            if out_start_sec is not None or out_end_sec is not None:
                out_strict = cls._pick_time_in_range(
                    punches,
                    start_sec=out_start_sec,
                    end_sec=out_end_sec,
                    pick="last",
                )

            # Nếu không match được gì trong window thì KHÔNG coi là ca này
            if in_strict is None and out_strict is None:
                continue

            in_val = in_strict
            if in_val is not None:
                cls._remove_first_occurrence(punches, in_val)

            # Out hiển thị: ưu tiên out_strict, nếu không có thì lấy overtime (relaxed)
            out_val = out_strict
            if out_val is None:
                out_val = _pick_out_relaxed(
                    punches,
                    shift=sh,
                    out_start_sec=out_start_sec,
                    out_end_sec=out_end_sec,
                )
            if out_val is not None:
                cls._remove_first_occurrence(punches, out_val)

            row[f"in_{pair_idx + 1}"] = in_val
            row[f"out_{pair_idx + 1}"] = out_val

            if in_val is not None or out_val is not None:
                used_any = True
                if _is_overnight_shift(sh):
                    used_night = True

            pair_idx += 1

        if used_any:
            row["shift_code"] = "Đêm" if used_night else "HC"

    @classmethod
    def _apply_mode_first_last_by_shifts(
        cls,
        row: dict[str, Any],
        *,
        shifts: list[dict[str, Any]],
    ) -> None:
        punches = cls._collect_sorted_times(row)
        for k in ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3"):
            row[k] = None
        if not punches:
            return

        def _is_overnight_shift(sh: dict[str, Any]) -> bool:
            tin = cls._time_to_seconds(sh.get("time_in"))
            tout = cls._time_to_seconds(sh.get("time_out"))
            if tin is not None and tout is not None and int(tout) < int(tin):
                return True
            win_in = cls._time_to_seconds(sh.get("in_window_start"))
            win_out = cls._time_to_seconds(sh.get("out_window_end"))
            if (
                win_in is not None
                and win_out is not None
                and int(win_out) < int(win_in)
            ):
                return True
            return False

        def _sec(v: object | None) -> int | None:
            return cls._time_to_seconds(v)

        def _match_shift_for_in(punch: object) -> dict[str, Any] | None:
            ps = cls._time_to_seconds(punch)
            if ps is None:
                return None

            best: dict[str, Any] | None = None
            best_score: int | None = None
            for sh in shifts or []:
                in_start = sh.get("in_window_start") or sh.get("time_in")
                in_end = sh.get("in_window_end") or sh.get("time_in")

                in_start_sec = _sec(in_start)
                in_end_sec = _sec(in_end)
                # Không cho match nếu window/time không có (tránh match nhầm mọi punch)
                if in_start_sec is None and in_end_sec is None:
                    continue
                if (
                    cls._pick_time_in_range(
                        [punch],
                        start_sec=in_start_sec,
                        end_sec=in_end_sec,
                        pick="first",
                    )
                    is None
                ):
                    continue

                base = cls._time_to_seconds(sh.get("time_in"))
                if base is None:
                    score = 0
                else:
                    score = abs(int(ps) - int(base))

                if best_score is None or score < best_score:
                    best = sh
                    best_score = score

            return best

        def _match_shift_for_out(punch: object) -> dict[str, Any] | None:
            ps = cls._time_to_seconds(punch)
            if ps is None:
                return None

            best: dict[str, Any] | None = None
            best_score: int | None = None
            for sh in shifts or []:
                out_start = sh.get("out_window_start") or sh.get("time_out")
                out_end = sh.get("out_window_end") or sh.get("time_out")

                out_start_sec = _sec(out_start)
                out_end_sec = _sec(out_end)
                # Không cho match nếu window/time không có (tránh match nhầm mọi punch)
                if out_start_sec is None and out_end_sec is None:
                    continue
                if (
                    cls._pick_time_in_range(
                        [punch],
                        start_sec=out_start_sec,
                        end_sec=out_end_sec,
                        pick="first",
                    )
                    is None
                ):
                    continue

                base = cls._time_to_seconds(sh.get("time_out"))
                if base is None:
                    score = 0
                else:
                    score = abs(int(ps) - int(base))

                if best_score is None or score < best_score:
                    best = sh
                    best_score = score

            return best

        def _pick_out_relaxed(
            values: list[object],
            *,
            shift: dict[str, Any],
        ) -> object | None:
            if not values:
                return None

            out_start = shift.get("out_window_start") or shift.get("time_out")
            out_end = shift.get("out_window_end") or shift.get("time_out")
            out_start_sec = cls._time_to_seconds(out_start)
            out_end_sec = cls._time_to_seconds(out_end)

            start = int(out_start_sec) if out_start_sec is not None else None
            is_night = _is_overnight_shift(shift)
            if not is_night:
                candidates: list[object] = []
                for v in values:
                    s = cls._time_to_seconds(v)
                    if s is None:
                        continue
                    if start is not None and int(s) < int(start):
                        continue
                    candidates.append(v)
                if not candidates:
                    return None
                return max(candidates, key=lambda v: int(cls._time_to_seconds(v) or 0))

            upper = 15 * 3600
            if out_end_sec is not None:
                try:
                    upper = max(int(upper), int(out_end_sec))
                except Exception:
                    pass
            if start is None:
                start = 0

            candidates2: list[object] = []
            for v in values:
                s = cls._time_to_seconds(v)
                if s is None:
                    continue
                if int(s) < int(start):
                    continue
                if int(s) > int(upper):
                    continue
                candidates2.append(v)
            if not candidates2:
                return None
            return max(candidates2, key=lambda v: int(cls._time_to_seconds(v) or 0))

        # Pick IN: earliest punch that matches ANY shift in-window
        punches_sorted = sorted(
            punches, key=lambda v: int(cls._time_to_seconds(v) or 0)
        )
        in_val = None
        in_shift: dict[str, Any] | None = None
        for p in punches_sorted:
            sh = _match_shift_for_in(p)
            if sh is not None:
                in_val = p
                in_shift = sh
                break
        if in_val is not None:
            cls._remove_first_occurrence(punches, in_val)

        # Pick OUT strict: latest punch that matches ANY shift out-window
        punches_sorted2 = sorted(
            punches,
            key=lambda v: int(cls._time_to_seconds(v) or 0),
            reverse=True,
        )
        out_strict = None
        out_shift: dict[str, Any] | None = None
        for p in punches_sorted2:
            sh = _match_shift_for_out(p)
            if sh is not None:
                out_strict = p
                out_shift = sh
                break

        out_val = out_strict
        if out_val is not None:
            cls._remove_first_occurrence(punches, out_val)
        else:
            # Relax overtime display: dựa trên shift đã match IN, nếu không có thì dùng shift match OUT (hiếm)
            base_shift = in_shift or out_shift
            if base_shift is not None:
                out_val = _pick_out_relaxed(punches, shift=base_shift)
                if out_val is not None:
                    cls._remove_first_occurrence(punches, out_val)

        row["in_1"] = in_val
        row["out_1"] = out_val

        def _is_overnight_shift(sh: dict[str, Any]) -> bool:
            tin = cls._time_to_seconds(sh.get("time_in"))
            tout = cls._time_to_seconds(sh.get("time_out"))
            if tin is not None and tout is not None and int(tout) < int(tin):
                return True
            win_in = cls._time_to_seconds(sh.get("in_window_start"))
            win_out = cls._time_to_seconds(sh.get("out_window_end"))
            if (
                win_in is not None
                and win_out is not None
                and int(win_out) < int(win_in)
            ):
                return True
            return False

        # Chỉ set ca khi có match trong window
        if shifts and (in_shift is not None or out_shift is not None):
            base = in_shift or out_shift
            row["shift_code"] = "Đêm" if _is_overnight_shift(base or {}) else "HC"

    @classmethod
    def _compute_shift_label_from_punches(
        cls,
        row: dict[str, Any],
        *,
        shifts: list[dict[str, Any]],
    ) -> str | None:
        punches = cls._collect_sorted_times(row)
        if not punches or not shifts:
            return None

        def _is_overnight_shift(sh: dict[str, Any]) -> bool:
            tin = cls._time_to_seconds(sh.get("time_in"))
            tout = cls._time_to_seconds(sh.get("time_out"))
            if tin is not None and tout is not None and int(tout) < int(tin):
                return True
            win_in = cls._time_to_seconds(sh.get("in_window_start"))
            win_out = cls._time_to_seconds(sh.get("out_window_end"))
            if (
                win_in is not None
                and win_out is not None
                and int(win_out) < int(win_in)
            ):
                return True
            return False

        def _sec(v: object | None) -> int | None:
            return cls._time_to_seconds(v)

        used_any = False
        used_night = False

        for sh in shifts:
            in_start = sh.get("in_window_start") or sh.get("time_in")
            in_end = sh.get("in_window_end") or sh.get("time_in")
            out_start = sh.get("out_window_start") or sh.get("time_out")
            out_end = sh.get("out_window_end") or sh.get("time_out")

            in_start_sec = _sec(in_start)
            in_end_sec = _sec(in_end)
            out_start_sec = _sec(out_start)
            out_end_sec = _sec(out_end)

            in_hit = None
            if in_start_sec is not None or in_end_sec is not None:
                in_hit = cls._pick_time_in_range(
                    punches,
                    start_sec=in_start_sec,
                    end_sec=in_end_sec,
                    pick="first",
                )

            out_hit = None
            if out_start_sec is not None or out_end_sec is not None:
                out_hit = cls._pick_time_in_range(
                    punches,
                    start_sec=out_start_sec,
                    end_sec=out_end_sec,
                    pick="first",
                )

            if in_hit is None and out_hit is None:
                continue

            used_any = True
            if _is_overnight_shift(sh):
                used_night = True

        if not used_any:
            return None
        return "Đêm" if used_night else "HC"

    @classmethod
    def _apply_mode_auto(cls, row: dict[str, Any]) -> None:
        sorted_vals = cls._collect_sorted_times(row)
        keys = ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3")
        for i, k in enumerate(keys):
            row[k] = sorted_vals[i] if i < len(sorted_vals) else None

    @classmethod
    def _apply_mode_first_last(cls, row: dict[str, Any]) -> None:
        sorted_vals = cls._collect_sorted_times(row)
        # Reset all
        for k in ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3"):
            row[k] = None
        if not sorted_vals:
            return
        row["in_1"] = sorted_vals[0]
        if len(sorted_vals) >= 2:
            row["out_1"] = sorted_vals[-1]

    def list_attendance_audit_arranged(
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
        rows = self._repo.list_rows(
            from_date=from_date,
            to_date=to_date,
            employee_id=employee_id,
            attendance_code=attendance_code,
            employee_ids=employee_ids,
            attendance_codes=attendance_codes,
            department_id=department_id,
            title_id=title_id,
        )

        # Holidays map (for day_key = 'holiday')
        holidays: set[str] = set()
        try:
            holidays = self._repo.list_holiday_dates(
                from_date=from_date, to_date=to_date
            )
        except Exception:
            holidays = set()

        # Map schedule_name -> {schedule_id, in_out_mode}
        schedule_names: list[str] = []
        for r in rows:
            name = str(r.get("schedule") or "").strip()
            if name:
                schedule_names.append(name)
        schedule_names = list(dict.fromkeys(schedule_names))

        schedule_map: dict[str, dict[str, Any]] = {}
        try:
            if schedule_names:
                schedule_map = self._repo.get_schedule_id_mode_by_names(schedule_names)
        except Exception:
            logger.exception("Không thể tải schedule_id/in_out_mode theo schedule_name")
            schedule_map = {}

        schedule_ids: list[int] = []
        for v in schedule_map.values():
            sid = v.get("schedule_id")
            if sid is None:
                continue
            try:
                schedule_ids.append(int(sid))
            except Exception:
                continue
        schedule_ids = list(dict.fromkeys(schedule_ids))

        details_map: dict[tuple[int, str], dict[str, Any]] = {}
        try:
            if schedule_ids:
                details_map = self._repo.get_schedule_details_by_schedule_ids(
                    schedule_ids
                )
        except Exception:
            logger.exception("Không thể tải arrange_schedule_details")
            details_map = {}

        all_shift_ids: list[int] = []
        for d in details_map.values():
            for k in ("shift1_id", "shift2_id", "shift3_id", "shift4_id", "shift5_id"):
                sid = d.get(k)
                if sid is None:
                    continue
                try:
                    all_shift_ids.append(int(sid))
                except Exception:
                    continue
        all_shift_ids = list(dict.fromkeys(all_shift_ids))

        shift_map: dict[int, dict[str, Any]] = {}
        try:
            if all_shift_ids:
                shift_map = self._repo.get_work_shifts_by_ids(all_shift_ids)
        except Exception:
            logger.exception("Không thể tải work_shifts")
            shift_map = {}

        # Persist shift_code after all post-processing.
        stored_code_by_audit_id: dict[int, str | None] = {}

        for r in rows:

            def _norm_code(v: object | None) -> str | None:
                s = str(v or "").strip()
                return s if s else None

            stored_code = _norm_code(r.get("shift_code_db"))
            # Mặc định: hiển thị giá trị DB (device mode), auto/first_last sẽ recompute.
            r["shift_code"] = stored_code
            try:
                if r.get("id") is not None:
                    stored_code_by_audit_id[int(r.get("id"))] = stored_code
            except Exception:
                pass

            schedule_name = str(r.get("schedule") or "").strip()
            meta = schedule_map.get(schedule_name) or {}
            mode = meta.get("in_out_mode")
            mode_norm = str(mode).strip().lower() if mode is not None else ""
            if mode_norm not in {"auto", "device", "first_last"}:
                mode_norm = "device"
            r["in_out_mode"] = mode_norm

            # Determine day_key for fetching schedule details
            day_key = self._date_to_day_key(r.get("date"))
            try:
                if r.get("date") is not None and str(r.get("date")) in holidays:
                    day_key = "holiday"
            except Exception:
                pass
            r["day_key"] = day_key

            schedule_id = meta.get("schedule_id")
            try:
                r["schedule_id"] = int(schedule_id) if schedule_id is not None else None
            except Exception:
                r["schedule_id"] = None

            # Build ordered shifts (shift1..shift5)
            shifts: list[dict[str, Any]] = []
            if r.get("schedule_id") is not None and day_key:
                detail = details_map.get((int(r.get("schedule_id")), str(day_key)))
                if detail is not None:
                    for k in (
                        "shift1_id",
                        "shift2_id",
                        "shift3_id",
                        "shift4_id",
                        "shift5_id",
                    ):
                        sid = detail.get(k)
                        if sid is None:
                            continue
                        try:
                            sh = shift_map.get(int(sid))
                            if sh is not None:
                                shifts.append(sh)
                        except Exception:
                            continue

            if mode_norm == "auto":
                if shifts:
                    # Không dùng lại giá trị DB cũ vì có thể đã bị lưu sai.
                    r["shift_code"] = None
                    self._apply_mode_auto_by_shifts(r, shifts=shifts)
                else:
                    self._apply_mode_auto(r)
            elif mode_norm == "first_last":
                if shifts:
                    # Không dùng lại giá trị DB cũ vì có thể đã bị lưu sai.
                    r["shift_code"] = None
                    self._apply_mode_first_last_by_shifts(r, shifts=shifts)
                else:
                    self._apply_mode_first_last(r)
            else:
                # device: giữ nguyên giờ nhưng vẫn tính Ca (HC/Đêm) theo work_shifts nếu có
                if shifts:
                    r["shift_code"] = self._compute_shift_label_from_punches(
                        r, shifts=shifts
                    )

        # Post-process: ca Đêm thường có giờ ra nằm ở ngày kế tiếp (buổi sáng).
        # Nếu ngày kế tiếp chỉ có punch buổi sáng (không có punch trong ngày), coi đó là phần dư của ca Đêm hôm trước
        # và không hiển thị ở ngày kế tiếp.
        try:
            by_emp: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                key = str(
                    r.get("employee_code")
                    or r.get("attendance_code")
                    or r.get("employee_id")
                    or ""
                ).strip()
                if not key:
                    continue
                by_emp.setdefault(key, []).append(r)

            def _row_date_key(v: object | None) -> str:
                if v is None:
                    return ""
                try:
                    return str(v)
                except Exception:
                    return ""

            def _row_time_values(row: dict[str, Any]) -> list[object]:
                out: list[object] = []
                for k in ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3"):
                    v = row.get(k)
                    if self._time_to_seconds(v) is None:
                        continue
                    out.append(v)
                return out

            MORNING_CUTOFF_SEC = 12 * 3600

            for emp_key, items in by_emp.items():
                items.sort(
                    key=lambda r: (
                        _row_date_key(r.get("date")),
                        int(r.get("id") or 0),
                    )
                )

                for i in range(1, len(items)):
                    prev = items[i - 1]
                    cur = items[i]
                    if str(prev.get("shift_code") or "").strip() != "Đêm":
                        continue

                    cur_times = _row_time_values(cur)
                    if not cur_times:
                        continue

                    secs = [self._time_to_seconds(v) for v in cur_times]
                    secs2 = [int(s) for s in secs if s is not None]
                    if not secs2:
                        continue

                    # Chỉ xử lý khi toàn bộ punch của ngày kế tiếp đều là buổi sáng.
                    if max(secs2) >= MORNING_CUTOFF_SEC:
                        continue

                    # Lấy punch buổi sáng muộn nhất để bổ sung cho giờ ra ca Đêm hôm trước (nếu cần).
                    best_time = max(
                        cur_times, key=lambda v: int(self._time_to_seconds(v) or 0)
                    )
                    prev_out = prev.get("out_1")
                    prev_out_sec = self._time_to_seconds(prev_out)
                    best_sec = self._time_to_seconds(best_time)

                    if best_sec is not None:
                        if prev_out_sec is None or int(best_sec) > int(prev_out_sec):
                            prev["out_1"] = best_time

                    # Clear toàn bộ punch của ngày kế tiếp để tránh hiển thị sai (vd Chủ nhật có 06:xx).
                    for k in ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3"):
                        cur[k] = None
                    cur["shift_code"] = None
        except Exception:
            logger.exception("Lỗi post-process ca Đêm qua ngày")

        pending_shift_code_updates: list[tuple[int, str | None]] = []
        for r in rows:

            def _norm_code2(v: object | None) -> str | None:
                s = str(v or "").strip()
                return s if s else None

            try:
                audit_id = r.get("id")
                if audit_id is None:
                    continue
                aid = int(audit_id)
                stored_code = stored_code_by_audit_id.get(aid)
                computed_code = _norm_code2(r.get("shift_code"))
                if computed_code != stored_code:
                    pending_shift_code_updates.append((aid, computed_code))
            except Exception:
                pass

        # Batch write shift_code xuống DB (không throw để tránh crash UI)
        if pending_shift_code_updates:
            try:
                self._repo.update_shift_codes(pending_shift_code_updates)
            except Exception:
                logger.exception("Không thể cập nhật shift_code vào attendance_audit")

        return rows
