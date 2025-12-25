"""ui.controllers.shift_attendance_controllers

Controller cho màn "Chấm công Theo ca".

Hiện tại:
- Load phòng ban vào combobox
- Load danh sách nhân viên (lọc có mcc_code) vào bảng MainContent1
- Nút "Làm mới" reset toàn bộ field của MainContent1
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QFileDialog, QDialog
from PySide6.QtWidgets import QTableWidgetItem

from export.export_details import export_shift_attendance_details_xlsx
from export.export_grid_list import CompanyInfo, export_shift_attendance_grid_xlsx
from services.arrange_schedule_services import ArrangeScheduleService
from services.company_services import CompanyService
from services.export_grid_list_services import (
    ExportGridListService,
    ExportGridListSettings,
)
from services.shift_attendance_services import ShiftAttendanceService
from ui.dialog.export_grid_list_dialog import ExportGridListDialog, NoteStyle
from ui.dialog.title_dialog import MessageDialog


logger = logging.getLogger(__name__)


class ShiftAttendanceController:
    def __init__(
        self,
        parent_window,
        content1,
        content2=None,
        service: ShiftAttendanceService | None = None,
    ) -> None:
        self._parent_window = parent_window
        self._content1 = content1
        self._content2 = content2
        self._service = service or ShiftAttendanceService()
        self._audit_mode: str = (
            "default"  # 'default' (dept/title) | 'selected' (checked)
        )

    def bind(self) -> None:
        self._content1.refresh_clicked.connect(self.on_refresh_clicked)
        self._content1.department_changed.connect(self.refresh)
        try:
            self._content1.title_changed.connect(self.refresh)
        except Exception:
            pass
        self._content1.search_changed.connect(self.refresh)
        if self._content2 is not None:
            self._content1.view_clicked.connect(self.on_view_clicked)
            try:
                self._content2.export_grid_clicked.connect(self.on_export_grid_clicked)
            except Exception:
                pass
            try:
                self._content2.detail_clicked.connect(self.on_export_detail_clicked)
            except Exception:
                pass

        # Initial
        self._load_departments()
        self._load_titles()
        self._reset_fields(clear_table=False)
        self.refresh()
        # Default: show ALL audit rows for current date range when opening.
        if self._content2 is not None:
            self._audit_mode = "default"
            self._load_audit_for_current_range(
                employee_ids=None,
                attendance_codes=None,
                department_id=None,
                title_id=None,
            )

    def on_export_grid_clicked(self) -> None:
        if self._content2 is None:
            return

        # If any row is checked (✅) in the table, export only checked rows.
        checked_rows: list[int] = []
        try:
            t = self._content2.table
            for r in range(int(t.rowCount())):
                it = t.item(int(r), 0)
                if it is None:
                    continue
                if str(it.text() or "").strip() == "✅":
                    checked_rows.append(int(r))
        except Exception:
            checked_rows = []

        # Load defaults: DB settings (if any) + company table fallback
        default_company = CompanyInfo()
        try:
            data = CompanyService().load_company()
            if data is not None:
                default_company = CompanyInfo(
                    name=str(data.company_name or "").strip(),
                    address=str(data.company_address or "").strip(),
                    phone=str(data.company_phone or "").strip(),
                )
        except Exception:
            default_company = CompanyInfo()

        export_service = ExportGridListService()
        saved = None
        try:
            saved = export_service.load()
        except Exception:
            saved = None

        dialog = ExportGridListDialog(
            self._parent_window, export_button_text="Xuất lưới"
        )
        dialog.set_values(
            company_name=(
                saved.company_name
                if saved and saved.company_name
                else default_company.name
            ),
            company_address=(
                saved.company_address
                if saved and saved.company_address
                else default_company.address
            ),
            company_phone=(
                saved.company_phone
                if saved and saved.company_phone
                else default_company.phone
            ),
            creator=(saved.creator if saved else ""),
            note_text=(saved.note_text if saved else ""),
            company_name_style=(
                NoteStyle(
                    font_size=(saved.company_name_font_size if saved else 13),
                    bold=(saved.company_name_bold if saved else False),
                    italic=(saved.company_name_italic if saved else False),
                    underline=(saved.company_name_underline if saved else False),
                    align=(saved.company_name_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            company_address_style=(
                NoteStyle(
                    font_size=(saved.company_address_font_size if saved else 13),
                    bold=(saved.company_address_bold if saved else False),
                    italic=(saved.company_address_italic if saved else False),
                    underline=(saved.company_address_underline if saved else False),
                    align=(saved.company_address_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            company_phone_style=(
                NoteStyle(
                    font_size=(saved.company_phone_font_size if saved else 13),
                    bold=(saved.company_phone_bold if saved else False),
                    italic=(saved.company_phone_italic if saved else False),
                    underline=(saved.company_phone_underline if saved else False),
                    align=(saved.company_phone_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            creator_style=(
                NoteStyle(
                    font_size=(saved.creator_font_size if saved else 13),
                    bold=(saved.creator_bold if saved else False),
                    italic=(saved.creator_italic if saved else False),
                    underline=(saved.creator_underline if saved else False),
                    align=(saved.creator_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            note_style=(
                NoteStyle(
                    font_size=(saved.note_font_size if saved else 13),
                    bold=(saved.note_bold if saved else False),
                    italic=(saved.note_italic if saved else False),
                    underline=(saved.note_underline if saved else False),
                    align=(saved.note_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
        )

        def _save_settings() -> tuple[bool, str]:
            vals = dialog.get_values()
            note_st = dialog.get_note_style()
            creator_st = dialog.get_creator_style()
            cn_st = dialog.get_company_name_style()
            ca_st = dialog.get_company_address_style()
            cp_st = dialog.get_company_phone_style()
            settings = ExportGridListSettings(
                company_name=vals.get("company_name", ""),
                company_address=vals.get("company_address", ""),
                company_phone=vals.get("company_phone", ""),
                company_name_font_size=int(cn_st.font_size),
                company_name_bold=bool(cn_st.bold),
                company_name_italic=bool(cn_st.italic),
                company_name_underline=bool(cn_st.underline),
                company_name_align=str(cn_st.align or "left"),
                company_address_font_size=int(ca_st.font_size),
                company_address_bold=bool(ca_st.bold),
                company_address_italic=bool(ca_st.italic),
                company_address_underline=bool(ca_st.underline),
                company_address_align=str(ca_st.align or "left"),
                company_phone_font_size=int(cp_st.font_size),
                company_phone_bold=bool(cp_st.bold),
                company_phone_italic=bool(cp_st.italic),
                company_phone_underline=bool(cp_st.underline),
                company_phone_align=str(cp_st.align or "left"),
                creator=vals.get("creator", ""),
                creator_font_size=int(creator_st.font_size),
                creator_bold=bool(creator_st.bold),
                creator_italic=bool(creator_st.italic),
                creator_underline=bool(creator_st.underline),
                creator_align=str(creator_st.align or "left"),
                note_text=vals.get("note_text", ""),
                note_font_size=int(note_st.font_size),
                note_bold=bool(note_st.bold),
                note_italic=bool(note_st.italic),
                note_underline=bool(note_st.underline),
                note_align=str(note_st.align or "left"),
            )
            # Preserve detail note when saving from Xuất lưới
            if saved is not None:
                settings = ExportGridListSettings(
                    company_name=settings.company_name,
                    company_address=settings.company_address,
                    company_phone=settings.company_phone,
                    company_name_font_size=settings.company_name_font_size,
                    company_name_bold=settings.company_name_bold,
                    company_name_italic=settings.company_name_italic,
                    company_name_underline=settings.company_name_underline,
                    company_name_align=settings.company_name_align,
                    company_address_font_size=settings.company_address_font_size,
                    company_address_bold=settings.company_address_bold,
                    company_address_italic=settings.company_address_italic,
                    company_address_underline=settings.company_address_underline,
                    company_address_align=settings.company_address_align,
                    company_phone_font_size=settings.company_phone_font_size,
                    company_phone_bold=settings.company_phone_bold,
                    company_phone_italic=settings.company_phone_italic,
                    company_phone_underline=settings.company_phone_underline,
                    company_phone_align=settings.company_phone_align,
                    creator=settings.creator,
                    creator_font_size=settings.creator_font_size,
                    creator_bold=settings.creator_bold,
                    creator_italic=settings.creator_italic,
                    creator_underline=settings.creator_underline,
                    creator_align=settings.creator_align,
                    note_text=settings.note_text,
                    note_font_size=settings.note_font_size,
                    note_bold=settings.note_bold,
                    note_italic=settings.note_italic,
                    note_underline=settings.note_underline,
                    note_align=settings.note_align,
                    detail_note_text=str(saved.detail_note_text or ""),
                    detail_note_font_size=int(saved.detail_note_font_size),
                    detail_note_bold=bool(saved.detail_note_bold),
                    detail_note_italic=bool(saved.detail_note_italic),
                    detail_note_underline=bool(saved.detail_note_underline),
                    detail_note_align=str(saved.detail_note_align or "left"),
                )
            ok, msg = export_service.save(settings, context="xuất lưới")
            dialog.set_status(msg, ok=ok)
            return ok, msg

        def _export_clicked() -> None:
            ok, _ = _save_settings()
            if not ok:
                return
            dialog.mark_export()
            dialog.accept()

        try:
            dialog.btn_save.clicked.connect(lambda: _save_settings())
            dialog.btn_export.clicked.connect(_export_clicked)
        except Exception:
            pass

        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.did_export():
            return

        vals = dialog.get_values()
        note_style = dialog.get_note_style()
        creator_style = dialog.get_creator_style()
        cn_style = dialog.get_company_name_style()
        ca_style = dialog.get_company_address_style()
        cp_style = dialog.get_company_phone_style()

        # Date range text
        try:
            from_qdate: QDate = self._content1.date_from.date()
            to_qdate: QDate = self._content1.date_to.date()
            from_txt = from_qdate.toString("dd/MM/yyyy")
            to_txt = to_qdate.toString("dd/MM/yyyy")
            from_file = from_qdate.toString("ddMMyyyy")
            to_file = to_qdate.toString("ddMMyyyy")
        except Exception:
            from_txt = ""
            to_txt = ""
            from_file = ""
            to_file = ""

        # Choose output file
        if from_file and to_file:
            default_name = f"Xuất Lưới_{from_file}_{to_file}.xlsx"
        else:
            default_name = "Xuất Lưới.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self._parent_window,
            "Xuất lưới chấm công",
            default_name,
            "Excel (*.xlsx)",
        )
        if not file_path:
            return

        company = CompanyInfo(
            name=str(vals.get("company_name", "") or "").strip(),
            address=str(vals.get("company_address", "") or "").strip(),
            phone=str(vals.get("company_phone", "") or "").strip(),
        )

        # Auto-hide unnecessary in/out columns based on Arrange Schedule in_out_mode.
        # Conservative rules to avoid losing data:
        # - If any schedule has mode 'device' OR unknown => keep all columns.
        # - If all schedules are 'first_last' => hide Vào/Ra 2-3.
        # - If any schedule is 'auto' (and none device/unknown) => hide pairs beyond max actually-used pair.
        force_exclude_headers: set[str] | None = None
        try:
            t = self._content2.table
            row_count = int(t.rowCount())
            rows_to_export = checked_rows if checked_rows else list(range(row_count))

            def _find_col(header_text: str) -> int | None:
                target = str(header_text or "").strip().lower()
                for c in range(int(t.columnCount())):
                    hi = t.horizontalHeaderItem(int(c))
                    ht = "" if hi is None else str(hi.text() or "")
                    if ht.strip().lower() == target:
                        return int(c)
                return None

            col_schedule = _find_col("Lịch làm việc")
            col_in2 = _find_col("Vào 2")
            col_out2 = _find_col("Ra 2")
            col_in3 = _find_col("Vào 3")
            col_out3 = _find_col("Ra 3")

            schedule_names: list[str] = []
            max_pair_used = 1

            for r in rows_to_export:
                rr = int(r)
                if rr < 0 or rr >= row_count:
                    continue

                if col_schedule is not None:
                    it = t.item(rr, int(col_schedule))
                    s = "" if it is None else str(it.text() or "").strip()
                    if s:
                        schedule_names.append(s)

                def _has_text(col: int | None) -> bool:
                    if col is None:
                        return False
                    it2 = t.item(rr, int(col))
                    return bool(str("" if it2 is None else it2.text() or "").strip())

                if _has_text(col_in3) or _has_text(col_out3):
                    max_pair_used = max(max_pair_used, 3)
                if _has_text(col_in2) or _has_text(col_out2):
                    max_pair_used = max(max_pair_used, 2)

            schedule_names = list(dict.fromkeys([s for s in schedule_names if s]))

            if schedule_names:
                mode_map = ArrangeScheduleService().get_in_out_mode_map(schedule_names)
                modes = [mode_map.get(n) for n in schedule_names]

                has_unknown = any(m is None for m in modes)
                has_device = any(m == "device" for m in modes)
                has_auto = any(m == "auto" for m in modes)

                if not has_unknown and not has_device:
                    if has_auto:
                        if max_pair_used <= 1:
                            force_exclude_headers = {"Vào 2", "Ra 2", "Vào 3", "Ra 3"}
                        elif max_pair_used == 2:
                            force_exclude_headers = {"Vào 3", "Ra 3"}
                    else:
                        # All first_last
                        force_exclude_headers = {"Vào 2", "Ra 2", "Vào 3", "Ra 3"}
        except Exception:
            force_exclude_headers = None

        ok, msg = export_shift_attendance_grid_xlsx(
            file_path=file_path,
            company=company,
            from_date_text=from_txt,
            to_date_text=to_txt,
            table=self._content2.table,
            row_indexes=(checked_rows if checked_rows else None),
            force_exclude_headers=force_exclude_headers,
            company_name_style={
                "font_size": int(cn_style.font_size),
                "bold": bool(cn_style.bold),
                "italic": bool(cn_style.italic),
                "underline": bool(cn_style.underline),
                "align": str(cn_style.align or "left"),
            },
            company_address_style={
                "font_size": int(ca_style.font_size),
                "bold": bool(ca_style.bold),
                "italic": bool(ca_style.italic),
                "underline": bool(ca_style.underline),
                "align": str(ca_style.align or "left"),
            },
            company_phone_style={
                "font_size": int(cp_style.font_size),
                "bold": bool(cp_style.bold),
                "italic": bool(cp_style.italic),
                "underline": bool(cp_style.underline),
                "align": str(cp_style.align or "left"),
            },
            creator=str(vals.get("creator", "") or "").strip(),
            creator_style={
                "font_size": int(creator_style.font_size),
                "bold": bool(creator_style.bold),
                "italic": bool(creator_style.italic),
                "underline": bool(creator_style.underline),
                "align": str(creator_style.align or "left"),
            },
            note_text=str(vals.get("note_text", "") or ""),
            note_style={
                "font_size": int(note_style.font_size),
                "bold": bool(note_style.bold),
                "italic": bool(note_style.italic),
                "underline": bool(note_style.underline),
                "align": str(note_style.align or "left"),
            },
        )
        MessageDialog.info(
            self._parent_window,
            "Xuất lưới chấm công",
            msg,
        )

    def on_export_detail_clicked(self) -> None:
        if self._content2 is None:
            return

        # If any row is checked (✅) in the table, export only checked rows.
        checked_rows: list[int] = []
        try:
            t = self._content2.table
            for r in range(int(t.rowCount())):
                it = t.item(int(r), 0)
                if it is None:
                    continue
                if str(it.text() or "").strip() == "✅":
                    checked_rows.append(int(r))
        except Exception:
            checked_rows = []

        # Load defaults: DB settings (if any) + company table fallback
        default_company = CompanyInfo()
        try:
            data = CompanyService().load_company()
            if data is not None:
                default_company = CompanyInfo(
                    name=str(data.company_name or "").strip(),
                    address=str(data.company_address or "").strip(),
                    phone=str(data.company_phone or "").strip(),
                )
        except Exception:
            default_company = CompanyInfo()

        export_service = ExportGridListService()
        saved = None
        try:
            saved = export_service.load()
        except Exception:
            saved = None

        dialog = ExportGridListDialog(
            self._parent_window, export_button_text="Xuất chi tiết"
        )
        dialog.set_values(
            company_name=(
                saved.company_name
                if saved and saved.company_name
                else default_company.name
            ),
            company_address=(
                saved.company_address
                if saved and saved.company_address
                else default_company.address
            ),
            company_phone=(
                saved.company_phone
                if saved and saved.company_phone
                else default_company.phone
            ),
            creator=(saved.creator if saved else ""),
            note_text=(saved.detail_note_text if saved else ""),
            company_name_style=(
                NoteStyle(
                    font_size=(saved.company_name_font_size if saved else 13),
                    bold=(saved.company_name_bold if saved else False),
                    italic=(saved.company_name_italic if saved else False),
                    underline=(saved.company_name_underline if saved else False),
                    align=(saved.company_name_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            company_address_style=(
                NoteStyle(
                    font_size=(saved.company_address_font_size if saved else 13),
                    bold=(saved.company_address_bold if saved else False),
                    italic=(saved.company_address_italic if saved else False),
                    underline=(saved.company_address_underline if saved else False),
                    align=(saved.company_address_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            company_phone_style=(
                NoteStyle(
                    font_size=(saved.company_phone_font_size if saved else 13),
                    bold=(saved.company_phone_bold if saved else False),
                    italic=(saved.company_phone_italic if saved else False),
                    underline=(saved.company_phone_underline if saved else False),
                    align=(saved.company_phone_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            creator_style=(
                NoteStyle(
                    font_size=(saved.creator_font_size if saved else 13),
                    bold=(saved.creator_bold if saved else False),
                    italic=(saved.creator_italic if saved else False),
                    underline=(saved.creator_underline if saved else False),
                    align=(saved.creator_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
            note_style=(
                NoteStyle(
                    font_size=(saved.detail_note_font_size if saved else 13),
                    bold=(saved.detail_note_bold if saved else False),
                    italic=(saved.detail_note_italic if saved else False),
                    underline=(saved.detail_note_underline if saved else False),
                    align=(saved.detail_note_align if saved else "left"),
                )
                if saved is not None
                else NoteStyle()
            ),
        )

        def _save_settings() -> tuple[bool, str]:
            vals = dialog.get_values()
            note_st = dialog.get_note_style()
            creator_st = dialog.get_creator_style()
            cn_st = dialog.get_company_name_style()
            ca_st = dialog.get_company_address_style()
            cp_st = dialog.get_company_phone_style()
            settings = ExportGridListSettings(
                company_name=vals.get("company_name", ""),
                company_address=vals.get("company_address", ""),
                company_phone=vals.get("company_phone", ""),
                company_name_font_size=int(cn_st.font_size),
                company_name_bold=bool(cn_st.bold),
                company_name_italic=bool(cn_st.italic),
                company_name_underline=bool(cn_st.underline),
                company_name_align=str(cn_st.align or "left"),
                company_address_font_size=int(ca_st.font_size),
                company_address_bold=bool(ca_st.bold),
                company_address_italic=bool(ca_st.italic),
                company_address_underline=bool(ca_st.underline),
                company_address_align=str(ca_st.align or "left"),
                company_phone_font_size=int(cp_st.font_size),
                company_phone_bold=bool(cp_st.bold),
                company_phone_italic=bool(cp_st.italic),
                company_phone_underline=bool(cp_st.underline),
                company_phone_align=str(cp_st.align or "left"),
                creator=vals.get("creator", ""),
                creator_font_size=int(creator_st.font_size),
                creator_bold=bool(creator_st.bold),
                creator_italic=bool(creator_st.italic),
                creator_underline=bool(creator_st.underline),
                creator_align=str(creator_st.align or "left"),
                # Preserve grid note when saving from Xuất chi tiết
                note_text=(saved.note_text if saved else ""),
                note_font_size=(saved.note_font_size if saved else 13),
                note_bold=(saved.note_bold if saved else False),
                note_italic=(saved.note_italic if saved else False),
                note_underline=(saved.note_underline if saved else False),
                note_align=(saved.note_align if saved else "left"),
                detail_note_text=vals.get("note_text", ""),
                detail_note_font_size=int(note_st.font_size),
                detail_note_bold=bool(note_st.bold),
                detail_note_italic=bool(note_st.italic),
                detail_note_underline=bool(note_st.underline),
                detail_note_align=str(note_st.align or "left"),
            )
            ok, msg = export_service.save(settings, context="xuất chi tiết")
            dialog.set_status(msg, ok=ok)
            return ok, msg

        def _export_clicked() -> None:
            ok, _ = _save_settings()
            if not ok:
                return
            dialog.mark_export()
            dialog.accept()

        try:
            dialog.btn_save.clicked.connect(lambda: _save_settings())
            dialog.btn_export.clicked.connect(_export_clicked)
        except Exception:
            pass

        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.did_export():
            return

        vals = dialog.get_values()
        note_style = dialog.get_note_style()
        creator_style = dialog.get_creator_style()
        cn_style = dialog.get_company_name_style()
        ca_style = dialog.get_company_address_style()
        cp_style = dialog.get_company_phone_style()

        # Date range text
        try:
            from_qdate: QDate = self._content1.date_from.date()
            to_qdate: QDate = self._content1.date_to.date()
            from_txt = from_qdate.toString("dd/MM/yyyy")
            to_txt = to_qdate.toString("dd/MM/yyyy")
            from_file = from_qdate.toString("ddMMyyyy")
            to_file = to_qdate.toString("ddMMyyyy")
        except Exception:
            from_txt = ""
            to_txt = ""
            from_file = ""
            to_file = ""

        # Choose output file
        if from_file and to_file:
            default_name = f"Xuất Chi Tiết_{from_file}_{to_file}.xlsx"
        else:
            default_name = "Xuất Chi Tiết.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self._parent_window,
            "Xuất chi tiết chấm công",
            default_name,
            "Excel (*.xlsx)",
        )
        if not file_path:
            return

        company = CompanyInfo(
            name=str(vals.get("company_name", "") or "").strip(),
            address=str(vals.get("company_address", "") or "").strip(),
            phone=str(vals.get("company_phone", "") or "").strip(),
        )

        ok, msg = export_shift_attendance_details_xlsx(
            file_path=file_path,
            company=company,
            from_date_text=from_txt,
            to_date_text=to_txt,
            table=self._content2.table,
            row_indexes=(checked_rows if checked_rows else None),
            company_name_style={
                "font_size": int(cn_style.font_size),
                "bold": bool(cn_style.bold),
                "italic": bool(cn_style.italic),
                "underline": bool(cn_style.underline),
                "align": str(cn_style.align or "left"),
            },
            company_address_style={
                "font_size": int(ca_style.font_size),
                "bold": bool(ca_style.bold),
                "italic": bool(ca_style.italic),
                "underline": bool(ca_style.underline),
                "align": str(ca_style.align or "left"),
            },
            company_phone_style={
                "font_size": int(cp_style.font_size),
                "bold": bool(cp_style.bold),
                "italic": bool(cp_style.italic),
                "underline": bool(cp_style.underline),
                "align": str(cp_style.align or "left"),
            },
            creator=str(vals.get("creator", "") or "").strip(),
            creator_style={
                "font_size": int(creator_style.font_size),
                "bold": bool(creator_style.bold),
                "italic": bool(creator_style.italic),
                "underline": bool(creator_style.underline),
                "align": str(creator_style.align or "left"),
            },
            note_text=str(vals.get("note_text", "") or ""),
            note_style={
                "font_size": int(note_style.font_size),
                "bold": bool(note_style.bold),
                "italic": bool(note_style.italic),
                "underline": bool(note_style.underline),
                "align": str(note_style.align or "left"),
            },
        )

        MessageDialog.info(
            self._parent_window,
            "Xuất chi tiết chấm công",
            msg,
        )

    def _current_date_range(self) -> tuple[str | None, str | None]:
        try:
            from_qdate: QDate = self._content1.date_from.date()
            to_qdate: QDate = self._content1.date_to.date()
            return (
                from_qdate.toString("yyyy-MM-dd"),
                to_qdate.toString("yyyy-MM-dd"),
            )
        except Exception:
            return (None, None)

    def _load_audit_for_current_range(
        self,
        *,
        employee_ids: list[int] | None,
        attendance_codes: list[str] | None,
        department_id: int | None,
        title_id: int | None,
    ) -> None:
        if self._content2 is None:
            return

        from_date, to_date = self._current_date_range()
        try:
            rows = self._service.list_attendance_audit(
                from_date=from_date,
                to_date=to_date,
                employee_ids=employee_ids,
                attendance_codes=attendance_codes,
                department_id=department_id,
                title_id=title_id,
            )
            self._render_audit_table(rows)
        except Exception:
            logger.exception("Không thể tải attendance_audit")
            try:
                self._content2.table.setRowCount(0)
            except Exception:
                pass

    def _load_departments(self) -> None:
        try:
            items = self._service.list_departments_dropdown() or []
        except Exception:
            logger.exception("Không thể tải danh sách phòng ban")
            items = []

        cb = self._content1.cbo_department
        old = cb.blockSignals(True)
        try:
            cb.clear()
            cb.addItem("Tất cả phòng ban", None)
            for dept_id, dept_name in items:
                # Hiển thị kèm ID để dễ đối soát
                cb.addItem(f"{dept_id} - {dept_name}", int(dept_id))
        finally:
            cb.blockSignals(old)

    def _load_titles(self) -> None:
        cb = getattr(self._content1, "cbo_title", None)
        if cb is None:
            return

        try:
            items = self._service.list_titles_dropdown() or []
        except Exception:
            logger.exception("Không thể tải danh sách chức vụ")
            items = []

        old = cb.blockSignals(True)
        try:
            cb.clear()
            cb.addItem("Tất cả chức vụ", None)
            for title_id, title_name in items:
                cb.addItem(f"{title_id} - {title_name}", int(title_id))
        finally:
            cb.blockSignals(old)

    def _selected_department_id(self) -> int | None:
        try:
            dept_id = self._content1.cbo_department.currentData()
            return int(dept_id) if dept_id else None
        except Exception:
            return None

    def _selected_title_id(self) -> int | None:
        try:
            cb = getattr(self._content1, "cbo_title", None)
            if cb is None:
                return None
            title_id = cb.currentData()
            return int(title_id) if title_id else None
        except Exception:
            return None

    def _build_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}

        filters["department_id"] = self._selected_department_id()
        filters["title_id"] = self._selected_title_id()

        search_by = self._content1.cbo_search_by.currentData()
        search_text = str(self._content1.inp_search_text.text() or "").strip()

        if search_by and search_text:
            filters["search_by"] = str(search_by)
            filters["search_text"] = search_text
        else:
            filters["search_by"] = None
            filters["search_text"] = None

        return filters

    def _reset_fields(self, *, clear_table: bool) -> None:
        # Reset inputs
        try:
            self._content1.cbo_department.setCurrentIndex(0)
        except Exception:
            pass
        try:
            self._content1.cbo_search_by.setCurrentIndex(0)
        except Exception:
            pass
        try:
            self._content1.inp_search_text.setText("")
        except Exception:
            pass

        # Reset dates
        today = QDate.currentDate()
        try:
            self._content1.date_from.setDate(today)
            self._content1.date_to.setDate(today)
        except Exception:
            pass

        # Reset counter/total + table
        try:
            self._content1.set_total(0)
        except Exception:
            pass
        if clear_table:
            try:
                self._content1.table.setRowCount(0)
            except Exception:
                pass

    def on_refresh_clicked(self) -> None:
        self._load_departments()
        self._load_titles()
        self._reset_fields(clear_table=True)
        self.refresh()
        # Default: show ALL audit rows for current date range after refresh.
        if self._content2 is not None:
            self._audit_mode = "default"
            self._load_audit_for_current_range(
                employee_ids=None,
                attendance_codes=None,
                department_id=None,
                title_id=None,
            )

    def refresh(self) -> None:
        try:
            rows = self._service.list_employees(self._build_filters())
            from_date, _to_date = self._current_date_range()
            schedule_map: dict[int, str] = {}
            if from_date:
                try:
                    emp_ids = [int(r.get("id")) for r in rows if r.get("id")]
                    schedule_map = self._service.get_employee_schedule_name_map(
                        employee_ids=emp_ids,
                        on_date=str(from_date),
                    )
                except Exception:
                    logger.exception("Không thể tải lịch làm việc của nhân viên")
                    schedule_map = {}

            self._render_main_table(rows, schedule_map=schedule_map)
            self._content1.set_total(len(rows))
        except Exception:
            logger.exception("Không thể tải danh sách nhân viên")
            try:
                self._content1.table.setRowCount(0)
            except Exception:
                pass
            try:
                self._content1.set_total(0)
            except Exception:
                pass

    def _render_main_table(
        self,
        rows: list[dict[str, Any]],
        *,
        schedule_map: dict[int, str] | None = None,
    ) -> None:
        table = self._content1.table
        table.setRowCount(0)
        if not rows:
            return

        schedule_map = schedule_map or {}

        # Columns: [✓] | STT | Mã NV | Tên nhân viên | Mã chấm công | Lịch trình | Chức vụ | Phòng Ban | Ngày vào làm
        table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            emp_id = r.get("id")
            dept_id = r.get("department_id")
            title_id = r.get("title_id")

            mcc_code = r.get("mcc_code")
            attendance_code = (
                str(mcc_code or "").strip() or str(r.get("employee_code") or "").strip()
            )

            chk = QTableWidgetItem("❌")
            chk.setFlags(chk.flags() & ~Qt.ItemFlag.ItemIsEditable)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            chk.setData(Qt.ItemDataRole.UserRole, emp_id)
            chk.setData(Qt.ItemDataRole.UserRole + 1, attendance_code)
            chk.setData(Qt.ItemDataRole.UserRole + 2, dept_id)
            chk.setData(Qt.ItemDataRole.UserRole + 3, title_id)
            table.setItem(r_idx, 0, chk)

            stt_val = r.get("stt")
            if stt_val is None or str(stt_val).strip() == "":
                stt_val = r_idx + 1
            stt_item = QTableWidgetItem(str(stt_val))
            stt_item.setFlags(stt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(r_idx, 1, stt_item)

            values = [
                r.get("employee_code"),
                r.get("full_name"),
                r.get("mcc_code"),
                schedule_map.get(int(emp_id), "") if emp_id is not None else "",
                r.get("title_name"),
                r.get("department_name"),
                r.get("start_date"),
            ]

            for c_idx, v in enumerate(values, start=2):
                item = QTableWidgetItem(str(v or ""))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c_idx == 2:
                    item.setData(Qt.ItemDataRole.UserRole, emp_id)
                    item.setData(Qt.ItemDataRole.UserRole + 1, dept_id)
                    item.setData(Qt.ItemDataRole.UserRole + 2, title_id)
                table.setItem(r_idx, c_idx, item)

        # Ensure per-column UI settings (align/bold/visible) apply to created items.
        try:
            self._content1.apply_ui_settings()
        except Exception:
            pass

    def _selected_employee_id(self) -> int | None:
        try:
            table = self._content1.table
            row = int(table.currentRow())
            if row < 0:
                return None
            item = table.item(row, 0)
            if item is None:
                return None
            emp_id = item.data(Qt.ItemDataRole.UserRole)
            return int(emp_id) if emp_id is not None else None
        except Exception:
            return None

    def _selected_attendance_code(self) -> str | None:
        """Returns selected employee attendance code (mcc_code) from MainContent1 table."""
        try:
            table = self._content1.table
            row = int(table.currentRow())
            if row < 0:
                return None
            # Column order in MainContent1: [✓], STT, employee_code, full_name, mcc_code, ...
            item = table.item(row, 4)
            if item is None:
                return None
            code = str(item.text() or "").strip()
            return code or None
        except Exception:
            return None

    def on_view_clicked(self) -> None:
        if self._content2 is None:
            return

        checked_ids: list[int] = []
        checked_codes: list[str] = []
        try:
            checked_ids, checked_codes = self._content1.get_checked_employee_keys()
        except Exception:
            checked_ids, checked_codes = ([], [])

        if checked_ids or checked_codes:
            self._audit_mode = "selected"
            self._load_audit_for_current_range(
                employee_ids=checked_ids,
                attendance_codes=checked_codes,
                department_id=None,
                title_id=None,
            )
            return

        # No checkbox selection: apply department/title filters.
        self._audit_mode = "default"
        self._load_audit_for_current_range(
            employee_ids=None,
            attendance_codes=None,
            department_id=self._selected_department_id(),
            title_id=self._selected_title_id(),
        )

    def _render_audit_table(self, rows: list[dict[str, Any]]) -> None:
        if self._content2 is None:
            return

        table = self._content2.table
        table.setRowCount(0)
        if not rows:
            return

        cols = [k for (k, _label) in getattr(self._content2, "_COLUMNS", [])]
        if not cols:
            return

        table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            for c_idx, key in enumerate(cols):
                # Virtual columns
                if key == "__check":
                    item = QTableWidgetItem("❌")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    try:
                        item.setData(Qt.ItemDataRole.UserRole, r.get("id"))
                    except Exception:
                        pass
                elif key == "stt":
                    stt_val = r.get("stt")
                    if stt_val is None or str(stt_val).strip() == "":
                        stt_val = r_idx + 1
                    item = QTableWidgetItem(str(stt_val))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    v = r.get(key)

                    # Allow MainContent2 to toggle HH:MM / HH:MM:SS for in/out columns.
                    if key in {"in_1", "out_1", "in_2", "out_2", "in_3", "out_3"}:
                        raw = "" if v is None else str(v)
                        try:
                            txt = self._content2._format_time_value(raw)  # type: ignore[attr-defined]
                        except Exception:
                            txt = raw
                        item = QTableWidgetItem(str(txt))
                        try:
                            item.setData(Qt.ItemDataRole.UserRole, raw)
                        except Exception:
                            pass
                    else:
                        item = QTableWidgetItem("" if v is None else str(v))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r_idx, c_idx, item)

        # Ensure per-column UI settings apply to created items.
        try:
            self._content2.apply_ui_settings()
        except Exception:
            pass
