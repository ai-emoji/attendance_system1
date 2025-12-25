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

    lm = _lunch_minutes(shift_row.get("lunch_start"), shift_row.get("lunch_end"))
    base = _minutes_between(shift_row.get("time_in"), shift_row.get("time_out"))
    net_from_times: int | None = None
    if base is not None:
        net_from_times = int(base) - int(lm)
        if net_from_times <= 0:
            net_from_times = int(base)

    # If DB has total_minutes, prefer it.
    # Support both interpretations:
    # - total_minutes is gross (includes lunch)  => subtract lunch
    # - total_minutes is net (already excludes)  => keep as-is
    try:
        tm = shift_row.get("total_minutes")
        if tm is not None and str(tm).strip() != "":
            v = int(float(tm))
            if v > 0:
                if base is not None and net_from_times is not None and int(lm) > 0:
                    # Decide by closeness to planned durations.
                    # Example: 08-17 (540), lunch 60 => net 480.
                    # tm=540 => treat gross -> 480; tm=480 => treat net -> 480.
                    dist_gross = abs(int(v) - int(base))
                    dist_net = abs(int(v) - int(net_from_times))
                    if dist_gross < dist_net:
                        req = int(v) - int(lm)
                        return int(req) if req > 0 else int(v)
                return int(v)
    except Exception:
        pass

    if base is None:
        return None

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


def _round_down_minutes_to_step(raw_minutes: int, step_minutes: int | None) -> int:
    """Round down minutes to a fixed step (e.g. 10 => 0,10,20,...).

    If step_minutes is None/0, returns raw_minutes.
    """

    try:
        m = int(raw_minutes)
    except Exception:
        return 0
    if m <= 0:
        return 0

    try:
        step = int(step_minutes or 0)
    except Exception:
        step = 0
    if step <= 0:
        return int(m)

    return int((m // step) * step)


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

    def _score(srow: dict[str, Any]) -> int | None:
        try:
            planned_start = _parse_time_to_seconds(srow.get("time_in"))
            planned_end_abs = _planned_end_abs_seconds_single(srow)
        except Exception:
            planned_start = None
            planned_end_abs = None
        if planned_start is None or planned_end_abs is None:
            return None
        actual_out_abs = _actual_out_abs_seconds(int(actual_out), int(planned_end_abs))
        return abs(int(actual_in) - int(planned_start)) + abs(
            int(actual_out_abs) - int(planned_end_abs)
        )

    # Prefer shifts whose in/out are within configured understanding windows,
    # but treat this as a SOFT preference to avoid wrong matching for early/late punches.
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

    best_all: dict[str, Any] | None = None
    best_all_score: int | None = None
    for srow in shift_rows:
        sc = _score(srow)
        if sc is None:
            continue
        if best_all_score is None or int(sc) < int(best_all_score):
            best_all_score = int(sc)
            best_all = srow

    best_match: dict[str, Any] | None = None
    best_match_score: int | None = None
    for srow in matching:
        sc = _score(srow)
        if sc is None:
            continue
        if best_match_score is None or int(sc) < int(best_match_score):
            best_match_score = int(sc)
            best_match = srow

    # If we have a window-matching shift and it's close to the best overall, use it.
    # Otherwise, fall back to the best overall by start/end closeness.
    if (
        best_match is not None
        and best_match_score is not None
        and best_all_score is not None
    ):
        window_slack_seconds = 60 * 60  # 60 minutes slack
        if int(best_match_score) <= int(best_all_score) + int(window_slack_seconds):
            return [best_match]

    return [best_all] if best_all is not None else list(shift_rows)


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


def _actual_in1_seconds(row: dict[str, Any]) -> int | None:
    return _parse_time_to_seconds((row or {}).get("in_1"))


def _actual_out1_seconds(row: dict[str, Any]) -> int | None:
    return _parse_time_to_seconds((row or {}).get("out_1"))


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


def _build_work_intervals_abs(
    pairs: list[tuple[object | None, object | None]],
) -> list[tuple[int, int]]:
    """Return work intervals as (start_sec, end_abs_sec) with overnight support."""

    out: list[tuple[int, int]] = []
    for t_in, t_out in pairs or []:
        s_in = _parse_time_to_seconds(t_in)
        s_out = _parse_time_to_seconds(t_out)
        if s_in is None or s_out is None:
            continue
        start = int(s_in)
        end = int(s_out)
        if end < start:
            end += 86400
        if end > start:
            out.append((start, end))
    return out


def _overlap_seconds(a0: int, a1: int, b0: int, b1: int) -> int:
    """Overlap length of [a0,a1] and [b0,b1] in seconds."""

    lo = max(int(a0), int(b0))
    hi = min(int(a1), int(b1))
    return int(hi - lo) if hi > lo else 0


def _lunch_interval_abs_for_shift(shift_row: dict[str, Any]) -> tuple[int, int] | None:
    if not shift_row:
        return None

    ls = _parse_time_to_seconds(shift_row.get("lunch_start"))
    le = _parse_time_to_seconds(shift_row.get("lunch_end"))
    if ls is None or le is None:
        return None

    try:
        planned_start = _parse_time_to_seconds(shift_row.get("time_in"))
        planned_end_abs = _planned_end_abs_seconds_single(shift_row)
    except Exception:
        planned_start = None
        planned_end_abs = None

    # Align lunch to the same absolute-day window as the shift if it is an overnight shift.
    if (
        planned_start is not None
        and planned_end_abs is not None
        and int(planned_end_abs) >= 86400
    ):
        if int(ls) < int(planned_start):
            ls = int(ls) + 86400
        if int(le) < int(planned_start):
            le = int(le) + 86400

    ls_i = int(ls)
    le_i = int(le)
    if le_i < ls_i:
        le_i += 86400
    if le_i <= ls_i:
        return None
    return (ls_i, le_i)


def _worked_seconds_excluding_lunch(
    pairs: list[tuple[object | None, object | None]],
    *,
    shift_row: dict[str, Any] | None,
) -> int:
    """Sum worked seconds from punch pairs, subtracting lunch overlap when configured."""

    intervals = _build_work_intervals_abs(pairs)
    if not intervals:
        return 0

    total = 0
    for a0, a1 in intervals:
        total += int(a1 - a0)

    if not shift_row:
        return int(max(0, total))

    lunch = _lunch_interval_abs_for_shift(shift_row)
    if lunch is None:
        return int(max(0, total))

    ls, le = lunch
    lunch_overlap = 0
    for a0, a1 in intervals:
        lunch_overlap += _overlap_seconds(int(a0), int(a1), int(ls), int(le))

    return int(max(0, total - lunch_overlap))


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
    absent: str = "V"  # vắng (C07)
    off: str = "OFF"  # ngày không xếp ca (C09)
    overnight_ok: str = "Đ"  # đúng giờ ca có qua đêm (C08)


class ShiftAttendanceMainContent2Service:
    """Enrich audit rows for MainContent2 display."""

    def __init__(self, symbol_service: AttendanceSymbolService | None = None) -> None:
        self._symbol_service = symbol_service or AttendanceSymbolService()
        self._cached_symbols: AttendanceSymbolMap | None = None

    def _load_symbols(self, *, force_reload: bool = False) -> AttendanceSymbolMap:
        # Symbols can be edited at runtime via the UI, so allow callers
        # to bypass caching and always fetch the latest values from DB.
        if (not force_reload) and self._cached_symbols is not None:
            return self._cached_symbols

        data = self._symbol_service.list_rows_by_code() or {}

        def _sym(code: str, default: str) -> str:
            """Return symbol text if visible; otherwise return empty string.

            Rule:
            - If the code exists in DB and is_visible != 1 => hidden => ""
            - If the code is missing (should not happen with seeded DB) => use default
            """

            row = data.get(code)
            if row is not None:
                try:
                    if int(row.get("is_visible") or 0) != 1:
                        return ""
                except Exception:
                    return ""
                v = str(row.get("symbol") or "").strip()
                return v or str(default).strip()
            return str(default).strip()

        # Defaults from seed: C05=KR (thiếu giờ ra), C06=KV (thiếu giờ vào)
        kr = _sym("C05", "KR")
        kv = _sym("C06", "KV")
        holiday = _sym("C10", "Le")
        absent = _sym("C07", "V")
        off = _sym("C09", "OFF")
        overnight_ok = _sym("C08", "Đ")

        self._cached_symbols = AttendanceSymbolMap(
            kr=kr,
            kv=kv,
            holiday=holiday,
            absent=absent,
            off=off,
            overnight_ok=overnight_ok,
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

        # Always refresh symbols from DB to reflect latest configuration.
        sym = self._load_symbols(force_reload=True)

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
                vv = (rr or {}).get(k)
                if (not _is_empty_time_value(vv)) and _parse_time_to_seconds(
                    vv
                ) is not None:
                    has_punch = True
                    break

            # 1) Fill KV/KR for missing in/out cells (only when there is at least one punch)
            if has_punch:
                for idx in (1, 2, 3):
                    k_in = f"in_{idx}"
                    k_out = f"out_{idx}"

                    v_in = rr.get(k_in)
                    v_out = rr.get(k_out)

                    empty_in = _is_empty_time_value(v_in)
                    empty_out = _is_empty_time_value(v_out)

                    # only fill when the other side exists
                    if empty_in and not empty_out:
                        if sym.kv:
                            rr[k_in] = sym.kv
                    if empty_out and not empty_in:
                        if sym.kr:
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
            is_overnight_matched_shift = False

            # V/OFF display rule (fill into in_1 only when there are NO punches):
            # - If work_date is a holiday => use C10 symbol (Le) in in_1
            # - Else, lookup schedule day shifts:
            #   - If the day declares any shift => use C07 symbol (V) in in_1
            #   - If the day declares no shift => use C09 symbol (OFF) in in_1
            schedule_name_for_rule = str(rr.get("schedule") or "").strip()
            effective_day_key: str | None = None
            has_scheduled_shift = False
            has_shift_on_actual_day = False
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
                    has_shift_on_actual_day = bool(declared_shift_ids)
                    effective_day_key = actual_key if actual_key in day_map else "sun"
                    shift_ids_for_rule = day_map.get(effective_day_key) or []
                    has_scheduled_shift = bool(shift_ids_for_rule)
            if effective_day_key is None and d:
                effective_day_key = _day_key_from_date(d)

            if (not has_punch) and _is_empty_time_value(rr.get("in_1")):
                if is_holiday:
                    if sym.holiday:
                        rr["in_1"] = sym.holiday
                else:
                    # If schedule is missing/unmapped, default to OFF.
                    if has_shift_on_actual_day:
                        if sym.absent:
                            rr["in_1"] = sym.absent
                    else:
                        if sym.off:
                            rr["in_1"] = sym.off

            # Holiday with no punches: skip late/early + planned hours/work calculations.
            mark_holiday = bool(is_holiday and (not has_punch))

            # Compute late/early when there are punches AND there is a declared shift for the day.
            if (
                (not mark_holiday)
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

                    # Rule per spec:
                    # - late if in_1 > time_in
                    # - early if time_out > out_1
                    # Choose matched shift (already filtered if multiple shifts).
                    matched = shift_rows[0] if shift_rows else None

                    planned_start = _shift_time_in_seconds(matched) if matched else None
                    planned_end_abs = (
                        _planned_end_abs_seconds_single(matched) if matched else None
                    )
                    if planned_end_abs is not None and int(planned_end_abs) >= 86400:
                        is_overnight_matched_shift = True

                    # Use the first in and last out across all punches.
                    actual_in = _actual_first_in_seconds(rr)
                    actual_out = _actual_last_out_seconds(rr)

                    if planned_start is not None and actual_in is not None:
                        actual_in_abs = int(actual_in)
                        if (
                            planned_end_abs is not None
                            and int(planned_end_abs) >= 86400
                        ):
                            # Overnight shift: treat after-midnight punch as +86400
                            if int(actual_in_abs) < int(planned_start):
                                actual_in_abs += 86400
                        diff = int(actual_in_abs) - int(planned_start)
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

            # Overnight on-time marker (C08): show in `leave` for night shifts.
            # Rule per request: use symbol 'Đ' for punches in overnight shift.
            # Do not overwrite existing leave values (e.g. real leave hours).
            if (
                has_punch
                and (not mark_holiday)
                and bool(is_overnight_matched_shift)
                and int(rr.get("late") or 0) == 0
                and int(rr.get("early") or 0) == 0
            ):
                cur_leave = rr.get("leave")
                if cur_leave is None or str(cur_leave or "").strip() == "":
                    if sym.overnight_ok:
                        rr["leave"] = sym.overnight_ok

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
                if mark_holiday:
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
                        # Rule:
                        # - Pick matched shift by schedule day + in/out windows.
                        # - Compute worked minutes (excluding lunch overlap).
                        # - If worked >= required(total_minutes):
                        #     hours = required_minutes/60, work = work_count
                        #     overtime = worked - required => hours_plus/work_plus
                        #   Else:
                        #     hours = worked/60, work = proportional to work_count
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

                            worked_sec = _worked_seconds_excluding_lunch(
                                clean_pairs,
                                shift_row=matched,
                            )
                            worked_min = int(worked_sec // 60) if worked_sec > 0 else 0

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

                            # Overtime rounding step in minutes (floor to step)
                            ot_step_min = (
                                _shift_overtime_round_minutes(matched)
                                if matched is not None
                                else 0
                            )
                            ot_step_min = int(ot_step_min or 0)

                            normal_min = int(worked_min)
                            ot_min = 0
                            if required_min is not None and int(required_min) > 0:
                                if int(worked_min) >= int(required_min):
                                    normal_min = int(required_min)
                                    ot_min = int(worked_min) - int(required_min)
                                else:
                                    normal_min = int(worked_min)
                                    ot_min = 0

                            ot_min_rounded = _round_down_minutes_to_step(
                                int(ot_min), ot_step_min
                            )

                            if need_hours:
                                rr["hours"] = (
                                    round(float(normal_min) / 60.0, 2)
                                    if normal_min > 0
                                    else 0
                                )
                                need_hours = False

                            if need_work:
                                if (
                                    required_min is not None
                                    and int(required_min) > 0
                                    and wc is not None
                                    and float(wc) > 0
                                ):
                                    if int(worked_min) >= int(required_min):
                                        rr["work"] = round(float(wc), 2)
                                    else:
                                        rr["work"] = round(
                                            (float(normal_min) / float(required_min))
                                            * float(wc),
                                            2,
                                        )
                                else:
                                    # Fallback (legacy): 8h = 1 công
                                    rr["work"] = round(
                                        (float(normal_min) / 60.0) / 8.0, 2
                                    )
                                need_work = False

                            if need_hours_plus:
                                rr["hours_plus"] = (
                                    round(float(ot_min_rounded) / 60.0, 2)
                                    if ot_min_rounded > 0
                                    else 0
                                )
                                need_hours_plus = False

                            if need_work_plus:
                                if (
                                    required_min is not None
                                    and int(required_min) > 0
                                    and wc is not None
                                    and float(wc) > 0
                                ):
                                    rr["work_plus"] = (
                                        round(
                                            (
                                                float(ot_min_rounded)
                                                / float(required_min)
                                            )
                                            * float(wc),
                                            2,
                                        )
                                        if ot_min_rounded > 0
                                        else 0
                                    )
                                else:
                                    rr["work_plus"] = round(
                                        (float(ot_min_rounded) / 60.0) / 8.0, 2
                                    )
                                need_work_plus = False

                        # If no punches, planned hours/work filling is handled earlier (0 display).

            # 2b) Overtime (Giờ +) is computed together with hours/work above
            # based on exceeded minutes vs shift required minutes.

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
