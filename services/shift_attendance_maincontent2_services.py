"""services.shift_attendance_maincontent2_services

Logic xử lý dữ liệu cho Shift Attendance - MainContent2.

Mục tiêu (theo yêu cầu):
- Kiểm tra giờ công (hours/work) và điền vào bảng khi DB chưa có.
- Đọc cấu trúc attendance_symbols (C01..C10) và dùng ký hiệu KV/KR
  (mặc định: C06=KV, C05=KR) để điền vào các ô thiếu giờ vào/ra.

Lưu ý:
- File này chỉ xử lý format/enrich dữ liệu để HIỂN THỊ; không ghi DB.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any

from services.attendance_symbol_services import AttendanceSymbolService


def _is_empty_time_value(v: object | None) -> bool:
    if v is None:
        return True
    s = str(v or "").strip()
    if not s:
        return True
    # Treat 00:00 or 00:00:00 as empty (often default/no punch)
    if s in {"00:00", "00:00:00", "0:00", "0:00:00"}:
        return True
    return False


def _parse_time_to_seconds(v: object | None) -> int | None:
    """Parse a time-like value into seconds since midnight.

    Supports:
    - datetime.time
    - datetime.timedelta (common MySQL TIME mapping)
    - strings: 'HH:MM', 'HH:MM:SS', 'YYYY-MM-DD HH:MM:SS'
    """

    if v is None:
        return None

    try:
        if isinstance(v, _dt.time):
            return int(v.hour) * 3600 + int(v.minute) * 60 + int(v.second)
    except Exception:
        pass

    try:
        if isinstance(v, _dt.timedelta):
            sec = int(v.total_seconds())
            # normalize to [0, 86400)
            sec = sec % 86400
            return sec
    except Exception:
        pass

    s = str(v or "").strip()
    if not s:
        return None

    # If datetime-like string, keep last token
    if " " in s:
        s = s.split()[-1].strip()

    # allow '08.30' -> '08:30'
    s = s.replace(".", ":")

    parts = [p for p in s.split(":") if p != ""]
    if len(parts) < 2:
        return None

    def _to_int(p: str) -> int:
        try:
            return int(p)
        except Exception:
            try:
                return int(float(p))
            except Exception:
                return 0

    hh = _to_int(parts[0])
    mm = _to_int(parts[1])
    ss = _to_int(parts[2][:2]) if len(parts) >= 3 else 0

    # Allow extended hours (e.g. 25:50) to represent next-day times on the same work_date.
    # Do not clamp to 23.
    hh = max(0, hh)
    mm = max(0, min(59, mm))
    ss = max(0, min(59, ss))

    return hh * 3600 + mm * 60 + ss


def _parse_iso_date(v: object | None) -> _dt.date | None:
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date) and not isinstance(v, _dt.datetime):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    token = s.split(" ", 1)[0].strip()
    # dd/MM/yyyy
    try:
        if "/" in token and len(token.split("/")) == 3:
            dd, mm, yy = token.split("/")
            return _dt.date(int(yy), int(mm), int(dd))
    except Exception:
        pass
    # yyyy-mm-dd
    try:
        return _dt.date.fromisoformat(token)
    except Exception:
        return None


def _day_key_from_date(d: _dt.date) -> str:
    # Mon=0..Sun=6
    w = int(d.weekday())
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
                    "thu" if w == 3 else "fri" if w == 4 else "sat" if w == 5 else "sun"
                )
            )
        )
    )


def _minutes_between(t_in: object | None, t_out: object | None) -> int | None:
    s_in = _parse_time_to_seconds(t_in)
    s_out = _parse_time_to_seconds(t_out)
    if s_in is None or s_out is None:
        return None
    dur = s_out - s_in
    if dur < 0:
        dur += 86400
    if dur <= 0:
        return None
    return int(dur // 60)


def _lunch_minutes(lunch_start: object | None, lunch_end: object | None) -> int:
    mi = _minutes_between(lunch_start, lunch_end)
    return int(mi or 0)


def _shift_effective_minutes(shift_row: dict[str, Any]) -> int | None:
    """Return planned minutes for a shift, subtracting lunch when possible."""

    if not shift_row:
        return None

    # If DB has total_minutes, prefer it.
    try:
        tm = shift_row.get("total_minutes")
        if tm is not None and str(tm).strip() != "":
            v = int(float(tm))
            if v > 0:
                return v
    except Exception:
        pass

    base = _minutes_between(shift_row.get("time_in"), shift_row.get("time_out"))
    if base is None:
        return None

    lm = _lunch_minutes(shift_row.get("lunch_start"), shift_row.get("lunch_end"))
    eff = int(base) - int(lm)
    return eff if eff > 0 else int(base)


def _shift_work_count(shift_row: dict[str, Any]) -> float | None:
    try:
        wc = shift_row.get("work_count")
        if wc is None or str(wc).strip() == "":
            return None
        return float(wc)
    except Exception:
        return None


def _shift_overtime_round_minutes(shift_row: dict[str, Any]) -> int | None:
    try:
        v = shift_row.get("overtime_round_minutes")
        if v is None or str(v).strip() == "":
            return None
        n = int(float(v))
        return n if n > 0 else 0
    except Exception:
        return None


def _round_minutes_to_30_blocks(raw_minutes: int, tol: int) -> int:
    """Round minutes to 30-minute blocks with ±tol snapping.

    Rule (conservative floor with snapping):
    - Let base = floor(raw/30)*30, next = base+30.
    - If within tol minutes of a block boundary, snap to that boundary.
      Example tol=5: 26->30 (snap up), 35->30 (snap down), 55->60 (snap up).
    - Otherwise keep base (do not overcount).
    """

    try:
        m = int(raw_minutes)
    except Exception:
        return 0
    if m <= 0:
        return 0
    try:
        t = max(0, int(tol))
    except Exception:
        t = 0

    step = 30
    base = (m // step) * step
    nxt = base + step

    # Snap down near base boundary (e.g. 35 within 5 of 30)
    if t > 0 and (m - base) <= t:
        return int(base)
    # Snap up near next boundary (e.g. 26 within 5 of 30)
    if t > 0 and (nxt - m) <= t:
        return int(nxt)
    return int(base)


def _shift_time_in_seconds(shift_row: dict[str, Any]) -> int | None:
    if not shift_row:
        return None
    return _parse_time_to_seconds(shift_row.get("time_in"))


def _shift_time_out_seconds(shift_row: dict[str, Any]) -> int | None:
    if not shift_row:
        return None
    return _parse_time_to_seconds(shift_row.get("time_out"))


def _planned_end_abs_seconds(shift_rows: list[dict[str, Any]]) -> int | None:
    """Latest planned end time (seconds). Supports overnight (+86400)."""

    ends: list[int] = []
    for srow in shift_rows or []:
        s_in = _shift_time_in_seconds(srow)
        s_out = _shift_time_out_seconds(srow)
        if s_in is None or s_out is None:
            continue
        end_abs = int(s_out)
        if int(s_out) < int(s_in):
            end_abs += 86400
        ends.append(end_abs)
    return int(max(ends)) if ends else None


def _planned_start_seconds(shift_rows: list[dict[str, Any]]) -> int | None:
    """Earliest planned start time (seconds since midnight)."""

    starts: list[int] = []
    for srow in shift_rows or []:
        s_in = _shift_time_in_seconds(srow)
        if s_in is None:
            continue
        starts.append(int(s_in))
    return int(min(starts)) if starts else None


def _planned_end_abs_seconds_single(shift_row: dict[str, Any]) -> int | None:
    """Planned end time for a single shift (seconds), supports overnight (+86400)."""

    try:
        s_in = _parse_time_to_seconds(shift_row.get("time_in"))
        s_out = _parse_time_to_seconds(shift_row.get("time_out"))
    except Exception:
        return None

    if s_in is None or s_out is None:
        return None
    if int(s_out) < int(s_in):
        return int(s_out) + 86400
    return int(s_out)


def _actual_out_abs_seconds(actual_out: int, planned_end_abs: int) -> int:
    """Normalize actual out to match overnight planned_end_abs when needed."""

    actual_out_abs = int(actual_out)
    if int(planned_end_abs) >= 86400 and actual_out_abs <= 12 * 3600:
        actual_out_abs += 86400
    return int(actual_out_abs)


def _time_in_window(sec: int, start: int | None, end: int | None) -> bool:
    """Check if time-of-day seconds falls within [start,end], supporting wrap-around."""

    if start is None or end is None:
        return True
    s = int(sec) % 86400
    a = int(start) % 86400
    b = int(end) % 86400
    if a <= b:
        return a <= s <= b
    # window wraps midnight
    return s >= a or s <= b


def _shift_window_seconds(shift_row: dict[str, Any], key: str) -> int | None:
    try:
        return _parse_time_to_seconds(shift_row.get(key))
    except Exception:
        return None


def _select_best_shift_rows(
    shift_rows: list[dict[str, Any]],
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pick the best matching shift for this row based on actual in/out.

    Used when a schedule day contains multiple shifts (e.g. day + night).
    """

    if not shift_rows or len(shift_rows) <= 1:
        return list(shift_rows or [])

    actual_in = _actual_first_in_seconds(row)
    actual_out = _actual_last_out_seconds(row)
    if actual_in is None or actual_out is None:
        return list(shift_rows)

    # Prefer shifts whose in/out are within configured understanding windows.
    matching: list[dict[str, Any]] = []
    for srow in shift_rows:
        in_ws = _shift_window_seconds(srow, "in_window_start")
        in_we = _shift_window_seconds(srow, "in_window_end")
        out_ws = _shift_window_seconds(srow, "out_window_start")
        out_we = _shift_window_seconds(srow, "out_window_end")

        if _time_in_window(int(actual_in), in_ws, in_we) and _time_in_window(
            int(actual_out), out_ws, out_we
        ):
            matching.append(srow)

    candidates = matching if matching else list(shift_rows)

    best_row: dict[str, Any] | None = None
    best_score: int | None = None

    for srow in candidates:
        try:
            planned_start = _parse_time_to_seconds(srow.get("time_in"))
            planned_end_abs = _planned_end_abs_seconds_single(srow)
        except Exception:
            planned_start = None
            planned_end_abs = None

        if planned_start is None or planned_end_abs is None:
            continue

        actual_out_abs = _actual_out_abs_seconds(int(actual_out), int(planned_end_abs))
        score = abs(int(actual_in) - int(planned_start)) + abs(
            int(actual_out_abs) - int(planned_end_abs)
        )

        if best_score is None or int(score) < int(best_score):
            best_score = int(score)
            best_row = srow

    return [best_row] if best_row is not None else list(shift_rows)


def _actual_first_in_seconds(row: dict[str, Any]) -> int | None:
    ins: list[int] = []
    for k in ("in_1", "in_2", "in_3"):
        s = _parse_time_to_seconds((row or {}).get(k))
        if s is None:
            continue
        ins.append(int(s))
    return int(min(ins)) if ins else None


def _actual_last_out_seconds(row: dict[str, Any]) -> int | None:
    outs: list[int] = []
    for k in ("out_1", "out_2", "out_3"):
        s = _parse_time_to_seconds((row or {}).get(k))
        if s is None:
            continue
        outs.append(int(s))
    return int(max(outs)) if outs else None


def _sum_work_seconds(pairs: list[tuple[object | None, object | None]]) -> int:
    total = 0
    for t_in, t_out in pairs:
        s_in = _parse_time_to_seconds(t_in)
        s_out = _parse_time_to_seconds(t_out)
        if s_in is None or s_out is None:
            continue
        dur = s_out - s_in
        if dur < 0:
            # overnight
            dur += 86400
        if dur > 0:
            total += dur
    return int(total)


def _shift_is_overnight(shift_row: dict[str, Any]) -> bool:
    s_in = _parse_time_to_seconds(shift_row.get("time_in"))
    s_out = _parse_time_to_seconds(shift_row.get("time_out"))
    if s_in is None or s_out is None:
        return False
    return int(s_out) < int(s_in)


def _shift_out_window_end_seconds(shift_row: dict[str, Any]) -> int | None:
    v = shift_row.get("out_window_end")
    s = _parse_time_to_seconds(v)
    if s is not None:
        return int(s)
    return _parse_time_to_seconds(shift_row.get("time_out"))


def _shift_in_window_end_seconds(shift_row: dict[str, Any]) -> int | None:
    v = shift_row.get("in_window_end")
    s = _parse_time_to_seconds(v)
    if s is not None:
        return int(s)
    # fallback: allow late check-in up to 03:00 for overnight shifts
    return 3 * 3600


def _abs_time_string_for_display(sec: int) -> str:
    sec = int(sec)
    if sec < 0:
        sec = 0
    hh = int(sec // 3600)
    mm = int((sec % 3600) // 60)
    ss = int(sec % 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


@dataclass
class AttendanceSymbolMap:
    kr: str = "KR"  # thiếu giờ ra
    kv: str = "KV"  # thiếu giờ vào
    holiday: str = "Le"  # nghỉ lễ (C10)
    absent: str = "V"  # vắng (mặc định không chấm công) (C07)


class ShiftAttendanceMainContent2Service:
    """Enrich audit rows for MainContent2 display."""

    def __init__(self, symbol_service: AttendanceSymbolService | None = None) -> None:
        self._symbol_service = symbol_service or AttendanceSymbolService()
        self._cached_symbols: AttendanceSymbolMap | None = None

    def _load_symbols(self) -> AttendanceSymbolMap:
        if self._cached_symbols is not None:
            return self._cached_symbols

        data = self._symbol_service.list_rows_by_code() or {}
        # Defaults from seed: C05=KR (thiếu giờ ra), C06=KV (thiếu giờ vào)
        kr = str((data.get("C05") or {}).get("symbol") or "KR").strip() or "KR"
        kv = str((data.get("C06") or {}).get("symbol") or "KV").strip() or "KV"
        holiday = str((data.get("C10") or {}).get("symbol") or "Le").strip() or "Le"
        absent = str((data.get("C07") or {}).get("symbol") or "V").strip() or "V"

        self._cached_symbols = AttendanceSymbolMap(
            kr=kr,
            kv=kv,
            holiday=holiday,
            absent=absent,
        )
        return self._cached_symbols

    @staticmethod
    def _to_decimal_hours(seconds: int) -> float:
        try:
            return round(float(seconds) / 3600.0, 2)
        except Exception:
            return 0.0

    def enrich_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        schedule_id_by_name: dict[str, int] | None = None,
        day_shift_ids_by_schedule_id: dict[int, dict[str, list[int]]] | None = None,
        work_shift_by_id: dict[int, dict[str, Any]] | None = None,
        holiday_dates: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []

        sym = self._load_symbols()

        # Normalize to mutable dicts so we can do cross-day adjustments for overnight shifts.
        src_rows: list[dict[str, Any]] = [dict(r or {}) for r in (rows or [])]

        def _row_code(rr: dict[str, Any]) -> str:
            c = str(rr.get("attendance_code") or "").strip()
            if c:
                return c
            return str(rr.get("employee_code") or "").strip()

        def _row_date(rr: dict[str, Any]) -> _dt.date | None:
            return _parse_iso_date(rr.get("date"))

        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for rr in src_rows:
            code = _row_code(rr)
            d0 = _row_date(rr)
            if not code or d0 is None:
                continue
            by_key[(code, d0.isoformat())] = rr

        def _get_day_shift_rows(
            rr: dict[str, Any], d0: _dt.date
        ) -> list[dict[str, Any]]:
            schedule_name = str(rr.get("schedule") or "").strip()
            if not (
                schedule_name
                and schedule_id_by_name
                and day_shift_ids_by_schedule_id
                and work_shift_by_id
            ):
                return []
            sched_id = schedule_id_by_name.get(schedule_name)
            if sched_id is None:
                return []
            day_map = day_shift_ids_by_schedule_id.get(int(sched_id)) or {}
            day_key = _day_key_from_date(d0)
            use_key = day_key if day_key in day_map else "sun"
            shift_ids = day_map.get(use_key) or []
            shift_rows: list[dict[str, Any]] = []
            for sid in shift_ids:
                try:
                    srow = work_shift_by_id.get(int(sid)) if work_shift_by_id else None
                except Exception:
                    srow = None
                if srow:
                    shift_rows.append(srow)
            return shift_rows

        # Overnight merge:
        # If schedule contains an overnight shift (e.g. 22:00->06:00), move early-morning punches
        # from next calendar day into previous work_date row.
        time_keys = ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3")
        for rr in src_rows:
            code = _row_code(rr)
            d0 = _row_date(rr)
            if not code or d0 is None:
                continue

            shift_rows_for_day = _get_day_shift_rows(rr, d0)
            overnight_rows = [s for s in shift_rows_for_day if _shift_is_overnight(s)]
            if not overnight_rows:
                continue

            # Use the first overnight shift as the association rule anchor.
            overnight_shift = overnight_rows[0]
            out_end = _shift_out_window_end_seconds(overnight_shift)
            in_end = _shift_in_window_end_seconds(overnight_shift)

            if out_end is None:
                continue

            # If out_window_end was configured, be strict; otherwise allow small tolerance.
            has_out_window_end = (
                _parse_time_to_seconds(overnight_shift.get("out_window_end"))
                is not None
            )
            tol = 0 if has_out_window_end else 60 * 60
            out_cutoff = int(out_end) + int(tol)

            next_day = (d0 + _dt.timedelta(days=1)).isoformat()
            rr_next = by_key.get((code, next_day))
            if rr_next is None:
                continue

            # Collect next-day time candidates that likely belong to previous overnight shift.
            candidates: list[tuple[int, str]] = []
            for k in time_keys:
                sec = _parse_time_to_seconds(rr_next.get(k))
                if sec is None:
                    continue
                # Only consider early morning times (0..12:00) and within out_cutoff.
                if int(sec) <= 12 * 3600 and int(sec) <= int(out_cutoff):
                    candidates.append((int(sec), k))

            if not candidates:
                continue
            candidates.sort(key=lambda x: x[0])

            # Determine if current row already has any in-time.
            has_any_in = any(
                _parse_time_to_seconds(rr.get(k)) is not None
                for k in ("in_1", "in_2", "in_3")
            )

            # Helper to find next empty slot.
            def _next_empty_slot(keys: tuple[str, ...]) -> str | None:
                for kk in keys:
                    if (
                        _parse_time_to_seconds(rr.get(kk)) is None
                        and str(rr.get(kk) or "").strip() == ""
                    ):
                        return kk
                    if _is_empty_time_value(rr.get(kk)):
                        return kk
                return None

            # If no in-time exists for the overnight shift day, move earliest candidate as in-time
            # when it is within in-window end.
            used_next_keys: set[str] = set()
            if not has_any_in and in_end is not None:
                in_slot = _next_empty_slot(("in_1", "in_2", "in_3"))
                if in_slot is not None:
                    for sec, k in candidates:
                        if k in used_next_keys:
                            continue
                        if int(sec) <= int(in_end):
                            # Display as 24+HH to show it's next-day time on the same work_date.
                            rr[in_slot] = _abs_time_string_for_display(86400 + int(sec))
                            used_next_keys.add(k)
                            break

            # Move the latest remaining candidate as out-time if current row doesn't have out-time.
            out_slot = _next_empty_slot(("out_1", "out_2", "out_3"))
            if out_slot is not None:
                remaining = [
                    (sec, k) for (sec, k) in candidates if k not in used_next_keys
                ]
                if remaining:
                    sec, k = remaining[-1]
                    # Keep out-time as normal HH:MM:SS
                    rr[out_slot] = _abs_time_string_for_display(int(sec))
                    used_next_keys.add(k)

            # Clear moved punches from next-day row so they don't double-count.
            for k in used_next_keys:
                try:
                    rr_next[k] = None
                except Exception:
                    pass

        out: list[dict[str, Any]] = []
        for r in src_rows:
            rr = dict(r or {})

            d = _parse_iso_date(rr.get("date"))
            date_iso = d.isoformat() if d else ""
            is_holiday = bool(date_iso and holiday_dates and date_iso in holiday_dates)

            has_punch = False
            for k in ("in_1", "out_1", "in_2", "out_2", "in_3", "out_3"):
                if _parse_time_to_seconds((rr or {}).get(k)) is not None:
                    has_punch = True
                    break

            # 1) Fill KV/KR for missing in/out cells
            for idx in (1, 2, 3):
                k_in = f"in_{idx}"
                k_out = f"out_{idx}"

                v_in = rr.get(k_in)
                v_out = rr.get(k_out)

                empty_in = _is_empty_time_value(v_in)
                empty_out = _is_empty_time_value(v_out)

                # only fill when the other side exists
                if empty_in and not empty_out:
                    rr[k_in] = sym.kv
                if empty_out and not empty_in:
                    rr[k_out] = sym.kr

            # 2) Compute hours/work when missing.
            # Prefer schedule+work_shifts (planned) to properly subtract lunch.
            need_hours = (
                rr.get("hours") is None or str(rr.get("hours") or "").strip() == ""
            )
            need_work = (
                rr.get("work") is None or str(rr.get("work") or "").strip() == ""
            )
            need_hours_plus = (
                rr.get("hours_plus") is None
                or str(rr.get("hours_plus") or "").strip() == ""
            )
            need_work_plus = (
                rr.get("work_plus") is None
                or str(rr.get("work_plus") or "").strip() == ""
            )

            # Late/Early minutes (will be displayed with C01/C02 symbols in UI).
            late_minutes = 0
            early_minutes = 0

            # Holiday/undeclared rule:
            # - If it's a holiday and there are NO punches, show holiday symbol in `leave`.
            # - Days not declared in schedule are treated as Sunday for schedule day lookup.
            # - If holiday has scheduled shift but no punches => holiday symbol.
            # - If holiday has punches => keep punches (no override).
            # - If day is NOT declared in schedule and NOT a holiday (and no punches) => fill C07.
            schedule_name_for_rule = str(rr.get("schedule") or "").strip()
            effective_day_key: str | None = None
            has_scheduled_shift = False
            is_undeclared_day = False
            if (
                schedule_name_for_rule
                and d
                and schedule_id_by_name
                and day_shift_ids_by_schedule_id
            ):
                sched_id = schedule_id_by_name.get(schedule_name_for_rule)
                if sched_id is not None:
                    day_map = day_shift_ids_by_schedule_id.get(int(sched_id)) or {}
                    actual_key = _day_key_from_date(d)
                    declared_shift_ids = day_map.get(actual_key) or []
                    # "Không được khai báo": không có key, hoặc có key nhưng không có ca.
                    is_undeclared_day = (actual_key not in day_map) or (
                        not declared_shift_ids
                    )
                    effective_day_key = actual_key if actual_key in day_map else "sun"
                    shift_ids_for_rule = day_map.get(effective_day_key) or []
                    has_scheduled_shift = bool(shift_ids_for_rule)
            if effective_day_key is None and d:
                effective_day_key = _day_key_from_date(d)

            mark_absent_c07 = bool(
                (not has_punch) and (not is_holiday) and is_undeclared_day
            )

            # Holiday: if the date is a holiday and there are NO punches, always mark holiday.
            # (Do not depend on schedule mapping; users expect KH shows lễ consistently.)
            mark_holiday = bool(is_holiday and (not has_punch))

            if mark_holiday:
                cur_leave = rr.get("leave")
                if cur_leave is None or str(cur_leave or "").strip() == "":
                    rr["leave"] = sym.holiday

            if mark_absent_c07 and not mark_holiday:
                cur_leave = rr.get("leave")
                if cur_leave is None or str(cur_leave or "").strip() == "":
                    rr["leave"] = sym.absent

            # Compute late/early when there are punches AND there is a declared shift for the day.
            if (
                (not mark_holiday)
                and (not mark_absent_c07)
                and has_punch
                and schedule_name_for_rule
                and d
                and schedule_id_by_name
                and day_shift_ids_by_schedule_id
                and work_shift_by_id
            ):
                sched_id = schedule_id_by_name.get(schedule_name_for_rule)
                if sched_id is not None:
                    day_map = day_shift_ids_by_schedule_id.get(int(sched_id)) or {}
                    day_key = _day_key_from_date(d)
                    use_key = day_key if day_key in day_map else "sun"
                    shift_ids = day_map.get(use_key) or []

                    shift_rows: list[dict[str, Any]] = []
                    for sid in shift_ids:
                        try:
                            srow = (
                                work_shift_by_id.get(int(sid))
                                if work_shift_by_id
                                else None
                            )
                        except Exception:
                            srow = None
                        if srow:
                            shift_rows.append(srow)

                    # If multiple shifts exist for the day, pick the one that matches
                    # actual punches (handles day vs night shifts).
                    if len(shift_rows) > 1:
                        shift_rows = _select_best_shift_rows(shift_rows, rr)

                    planned_start = _planned_start_seconds(shift_rows)
                    planned_end_abs = _planned_end_abs_seconds(shift_rows)
                    actual_in = _actual_first_in_seconds(rr)
                    actual_out = _actual_last_out_seconds(rr)

                    if planned_start is not None and actual_in is not None:
                        diff = int(actual_in) - int(planned_start)
                        if diff > 0:
                            late_minutes = int(diff // 60)

                    if planned_end_abs is not None and actual_out is not None:
                        actual_out_abs = _actual_out_abs_seconds(
                            int(actual_out), int(planned_end_abs)
                        )
                        diff2 = int(planned_end_abs) - int(actual_out_abs)
                        if diff2 > 0:
                            early_minutes = int(diff2 // 60)

            # Normalize output: if not late/early => 0
            rr["late"] = int(late_minutes) if int(late_minutes) > 0 else 0
            rr["early"] = int(early_minutes) if int(early_minutes) > 0 else 0

            # If there are no punches at all, do not compute planned hours/work from schedule.
            # Display 0 for giờ/công (+) when missing.
            if not has_punch:
                if need_hours:
                    rr["hours"] = 0
                    need_hours = False
                if need_work:
                    rr["work"] = 0
                    need_work = False
                if need_hours_plus:
                    rr["hours_plus"] = 0
                    need_hours_plus = False
                if need_work_plus:
                    rr["work_plus"] = 0
                    need_work_plus = False

            if need_hours or need_work:
                schedule_name = str(rr.get("schedule") or "").strip()
                # For holiday with no punches, do not auto-fill planned hours/work.
                if mark_holiday or mark_absent_c07:
                    schedule_name = ""
                if (
                    schedule_name
                    and d
                    and schedule_id_by_name
                    and day_shift_ids_by_schedule_id
                    and work_shift_by_id
                ):
                    sched_id = schedule_id_by_name.get(schedule_name)
                    if sched_id is not None:
                        day_map = day_shift_ids_by_schedule_id.get(int(sched_id)) or {}
                        day_key = _day_key_from_date(d)
                        # Treat non-declared days as Sunday
                        use_key = day_key if day_key in day_map else "sun"
                        shift_ids = day_map.get(use_key) or []

                        # Build shift rows for the day.
                        shift_rows: list[dict[str, Any]] = []
                        for sid in shift_ids:
                            srow = (
                                work_shift_by_id.get(int(sid))
                                if work_shift_by_id
                                else None
                            )
                            if srow:
                                shift_rows.append(srow)

                        # When there are punches, compute hours from actual punches.
                        # Work is awarded (1 công / nửa công) only when actual minutes
                        # meet the configured required minutes of the matched shift.
                        if has_punch and shift_rows:
                            matched_rows = (
                                _select_best_shift_rows(shift_rows, rr)
                                if len(shift_rows) > 1
                                else shift_rows
                            )
                            matched = matched_rows[0] if matched_rows else None

                            pairs = [
                                (rr.get("in_1"), rr.get("out_1")),
                                (rr.get("in_2"), rr.get("out_2")),
                                (rr.get("in_3"), rr.get("out_3")),
                            ]
                            clean_pairs: list[tuple[object | None, object | None]] = []
                            for a, b in pairs:
                                if (
                                    _parse_time_to_seconds(a) is None
                                    or _parse_time_to_seconds(b) is None
                                ):
                                    continue
                                clean_pairs.append((a, b))

                            worked_sec = _sum_work_seconds(clean_pairs)
                            worked_min = int(worked_sec // 60) if worked_sec > 0 else 0
                            worked_hours = (
                                round(float(worked_min) / 60.0, 2)
                                if worked_min > 0
                                else 0
                            )

                            if need_hours:
                                rr["hours"] = worked_hours
                                need_hours = False

                            if need_work:
                                required_min = (
                                    _shift_effective_minutes(matched)
                                    if matched is not None
                                    else None
                                )
                                wc = (
                                    _shift_work_count(matched)
                                    if matched is not None
                                    else None
                                )

                                if (
                                    required_min is not None
                                    and int(required_min) > 0
                                    and worked_min >= int(required_min)
                                    and wc is not None
                                    and float(wc) > 0
                                ):
                                    rr["work"] = round(float(wc), 2)
                                else:
                                    # Not enough minutes: show partial work from hours.
                                    rr["work"] = round(float(worked_hours) / 8.0, 2)
                                need_work = False

                        # If no punches, planned hours/work filling is handled earlier (0 display).

            # 2b) Compute overtime (Giờ +) when missing: actual last out after planned end.
            if need_hours_plus or need_work_plus:
                schedule_name = str(rr.get("schedule") or "").strip()
                # For holiday with no punches, do not compute overtime.
                if mark_holiday or mark_absent_c07:
                    schedule_name = ""
                if (
                    schedule_name
                    and d
                    and schedule_id_by_name
                    and day_shift_ids_by_schedule_id
                    and work_shift_by_id
                ):
                    sched_id = schedule_id_by_name.get(schedule_name)
                    if sched_id is not None:
                        day_map = day_shift_ids_by_schedule_id.get(int(sched_id)) or {}
                        day_key = _day_key_from_date(d)
                        # Treat non-declared days as Sunday
                        use_key = day_key if day_key in day_map else "sun"
                        shift_ids = day_map.get(use_key) or []

                        shift_rows: list[dict[str, Any]] = []
                        for sid in shift_ids:
                            srow = (
                                work_shift_by_id.get(int(sid))
                                if work_shift_by_id
                                else None
                            )
                            if srow:
                                shift_rows.append(srow)

                        # If multiple shifts, compute overtime against the matched shift.
                        if has_punch and len(shift_rows) > 1:
                            shift_rows = _select_best_shift_rows(shift_rows, rr)

                        planned_start = _planned_start_seconds(shift_rows)
                        planned_end_abs = _planned_end_abs_seconds(shift_rows)
                        actual_in = _actual_first_in_seconds(rr)
                        actual_out = _actual_last_out_seconds(rr)

                        # Tolerance minutes for rounding (use max configured among shifts).
                        tol_min = 0
                        for srow in shift_rows:
                            v = _shift_overtime_round_minutes(srow)
                            if v is not None and int(v) > int(tol_min):
                                tol_min = int(v)

                        early_min = 0
                        late_min = 0

                        # Early check-in before planned start counts as overtime too.
                        if planned_start is not None and actual_in is not None:
                            diff = int(planned_start) - int(actual_in)
                            if diff > 0:
                                early_min = int(diff // 60)

                        # Late check-out after planned end counts as overtime.
                        if planned_end_abs is not None and actual_out is not None:
                            actual_out_abs = _actual_out_abs_seconds(
                                int(actual_out), int(planned_end_abs)
                            )
                            diff2 = int(actual_out_abs) - int(planned_end_abs)
                            if diff2 > 0:
                                late_min = int(diff2 // 60)

                        # Round each side to 30-minute blocks with ±tol.
                        early_rounded = _round_minutes_to_30_blocks(early_min, tol_min)
                        late_rounded = _round_minutes_to_30_blocks(late_min, tol_min)
                        total_ot_minutes = int(early_rounded) + int(late_rounded)

                        if total_ot_minutes > 0:
                            ot_hours = round(float(total_ot_minutes) / 60.0, 2)
                            if need_hours_plus:
                                rr["hours_plus"] = ot_hours
                                need_hours_plus = False
                            if need_work_plus:
                                rr["work_plus"] = round(float(ot_hours) / 8.0, 2)
                                need_work_plus = False

            # Fallback: compute from punches if still missing.
            if need_hours:
                pairs = [
                    (rr.get("in_1"), rr.get("out_1")),
                    (rr.get("in_2"), rr.get("out_2")),
                    (rr.get("in_3"), rr.get("out_3")),
                ]

                clean_pairs: list[tuple[object | None, object | None]] = []
                for a, b in pairs:
                    if (
                        _parse_time_to_seconds(a) is None
                        or _parse_time_to_seconds(b) is None
                    ):
                        continue
                    clean_pairs.append((a, b))

                sec = _sum_work_seconds(clean_pairs)
                if sec > 0:
                    rr["hours"] = self._to_decimal_hours(sec)

            if need_work:
                try:
                    h = rr.get("hours")
                    if h is not None and str(h).strip() != "":
                        hh = float(h)
                        rr["work"] = round(hh / 8.0, 2)
                except Exception:
                    pass

            out.append(rr)

        return out
