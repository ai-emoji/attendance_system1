"""ui.controllers.schedule_work_controllers

Controller cho màn "Sắp xếp lịch Làm việc".

Hiện tại (theo spec UI-only):
- Load cây Phòng ban/Chức danh (bên trái)
- Wire buttons ở TitleBar2: Tìm kiếm / Làm mới / Xóa lịch NV
- Bên phải đang là placeholder table (chưa render dữ liệu)

Không dùng QMessageBox; dùng MessageDialog.
"""

from __future__ import annotations

import logging

from services.schedule_work_services import ScheduleWorkService
from ui.dialog.title_dialog import MessageDialog


logger = logging.getLogger(__name__)


class ScheduleWorkController:
    def __init__(
        self,
        parent_window,
        view,
        service: ScheduleWorkService | None = None,
    ) -> None:
        self._parent_window = parent_window
        self._view = view
        self._service = service or ScheduleWorkService()

        # Cache search result (UI table will be implemented later)
        self._employees_cache = []

    def bind(self) -> None:
        try:
            self._view.title2.search_clicked.connect(self.on_search)
            self._view.title2.refresh_clicked.connect(self.on_refresh)
            self._view.title2.delete_clicked.connect(self.on_delete)
        except Exception:
            pass

        try:
            self._view.content.right.btn_apply.clicked.connect(self.on_apply)
        except Exception:
            pass

        # Load tree on first show
        self.refresh_tree()
        self.refresh_schedules()

        # Load initial employee list from DB (same columns shown in the right table).
        # This mirrors the Employee screen behavior: show data immediately, user can refine via Search.
        self.on_search()

    def refresh_tree(self) -> None:
        try:
            dept_rows = self._service.list_departments_tree_rows()
            title_rows = self._service.list_titles_tree_rows()
            self._view.content.left.set_departments(dept_rows, titles=title_rows)
        except Exception:
            logger.exception("Không thể tải cây phòng ban/chức danh")
            try:
                self._view.content.left.set_departments([], titles=[])
            except Exception:
                pass

    def refresh_schedules(self) -> None:
        try:
            items = self._service.list_schedules()
            self._view.content.right.set_schedules(items)
            try:
                self._view.content.temp.set_schedules(items)
            except Exception:
                pass
        except Exception:
            logger.exception("Không thể tải danh sách lịch làm việc")
            try:
                self._view.content.right.set_schedules([])
                try:
                    self._view.content.temp.set_schedules([])
                except Exception:
                    pass
            except Exception:
                pass

    def on_refresh(self) -> None:
        self._employees_cache = []
        self.refresh_tree()
        self.refresh_schedules()
        try:
            self._view.title2.set_total(0)
            self._view.content.right.clear_employees()
        except Exception:
            pass

    def _get_selected_filters(self) -> dict:
        filters: dict = {
            "search_by": None,
            "search_text": None,
            "department_id": None,
            "title_id": None,
        }

        try:
            filters["search_by"] = self._view.title2.cbo_search_by.currentData()
            filters["search_text"] = self._view.title2.inp_search.text()
        except Exception:
            pass

        # Left tree selection
        try:
            ctx = self._view.content.left.get_selected_node_context() or {}
            if ctx.get("type") == "dept":
                filters["department_id"] = ctx.get("id")
            elif ctx.get("type") == "title":
                filters["title_id"] = ctx.get("id")
                filters["department_id"] = ctx.get("department_id")
        except Exception:
            pass

        return filters

    def on_search(self) -> None:
        try:
            filters = self._get_selected_filters()
            rows = self._service.search_employees(filters)
            self._employees_cache = list(rows)
            self._view.title2.set_total(len(self._employees_cache))
            self._view.content.right.set_employees(self._employees_cache)

            # Load lịch làm việc đã gán từ DB để không bị mất khi mở lại.
            try:
                emp_ids = []
                for x in self._employees_cache:
                    try:
                        if isinstance(x, dict):
                            emp_ids.append(int(x.get("id") or 0))
                        else:
                            emp_ids.append(int(getattr(x, "id", None) or 0))
                    except Exception:
                        continue
                emp_ids = [i for i in emp_ids if i > 0]
                schedule_map = self._service.get_employee_schedule_name_map(emp_ids)
                self._view.content.right.apply_schedule_name_map(schedule_map)
            except Exception:
                logger.exception("Không thể tải lịch làm việc đã gán")
        except Exception:
            logger.exception("Không thể tìm nhân viên")
            try:
                self._view.title2.set_total(0)
                self._view.content.right.clear_employees()
            except Exception:
                pass

    def on_apply(self) -> None:
        try:
            cbo = self._view.content.right.cbo_schedule
            schedule_name = str(cbo.currentText() or "").strip()
            schedule_id = cbo.currentData()

            # Index 0 is placeholder: must choose an action/schedule
            try:
                if int(cbo.currentIndex()) == 0:
                    MessageDialog.info(
                        self._parent_window,
                        "Thông báo",
                        "Vui lòng chọn Lịch làm việc trước khi Áp dụng.",
                    )
                    return
            except Exception:
                pass

            checked_ids = self._view.content.right.get_checked_employee_ids()
            if not checked_ids:
                MessageDialog.info(
                    self._parent_window,
                    "Thông báo",
                    "Vui lòng chọn nhân viên trước khi Áp dụng.",
                )
                return

            # Option "Chưa sắp xếp ca" (data=0): clear assignments
            try:
                if int(schedule_id or 0) == 0:
                    for emp_id in checked_ids:
                        try:
                            self._service.delete_employee_schedule(int(emp_id))
                        except Exception:
                            pass
                    self._view.content.right.apply_schedule_to_checked("")
                    self._view.title2.set_total(
                        self._view.content.right.table.rowCount()
                    )
                    return
            except Exception:
                pass

            # Persist to DB (effective from today) then reflect in UI.
            try:
                processed = self._service.apply_schedule_to_employees(
                    employee_ids=[int(x) for x in checked_ids],
                    schedule_id=int(schedule_id),
                )
                if int(processed or 0) <= 0:
                    MessageDialog.info(
                        self._parent_window,
                        "Thông báo",
                        "Không thể cập nhật Lịch làm việc vào DB. Vui lòng kiểm tra cấu hình DB và thử lại.",
                    )
                    return
            except Exception:
                logger.exception("Không thể cập nhật lịch làm việc vào DB")
                MessageDialog.info(
                    self._parent_window,
                    "Thông báo",
                    "Không thể cập nhật Lịch làm việc vào DB. Vui lòng kiểm tra cấu hình DB và thử lại.",
                )
                return

            applied = self._view.content.right.apply_schedule_to_checked(schedule_name)
            self._view.title2.set_total(self._view.content.right.table.rowCount())
            if applied <= 0:
                MessageDialog.info(
                    self._parent_window,
                    "Thông báo",
                    "Không có nhân viên nào được áp dụng.",
                )
        except Exception:
            logger.exception("Không thể áp dụng lịch làm việc")

    def on_delete(self) -> None:
        try:
            checked_ids = self._view.content.right.get_checked_employee_ids()
            if not checked_ids:
                MessageDialog.info(
                    self._parent_window,
                    "Thông báo",
                    "Vui lòng chọn nhân viên trước khi Xóa lịch NV.",
                )
                return

            # Best-effort delete in DB; UI schedule column will be cleared.
            for emp_id in checked_ids:
                try:
                    self._service.delete_employee_schedule(int(emp_id))
                except Exception:
                    pass

            # Clear schedule column for checked rows
            self._view.content.right.apply_schedule_to_checked("")
        except Exception:
            logger.exception("Không thể xóa lịch NV")
