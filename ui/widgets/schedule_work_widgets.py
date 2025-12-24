"""ui.widgets.schedule_work_widgets

UI cho màn "Sắp xếp lịch Làm việc".

Yêu cầu (UI-only, chưa có nghiệp vụ):
- Sao chép TitleBar1
- TitleBar2: input tìm kiếm + combobox chọn tìm kiếm theo (Mã NV/Tên nhân viên)
    + button Tìm kiếm + button Làm mới + button Xóa lịch NV + hiển thị Tổng
- MainContent chia 2 phần:
    - Bên trái: fixed width 400, min height 254, hiển thị cây Phòng ban/Chức danh
    - Bên phải: min width 1200, min height 254, để trống (placeholder)
"""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QDate, QLocale, QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.resource import (
    BG_TITLE_1_HEIGHT,
    BG_TITLE_2_HEIGHT,
    COLOR_BORDER,
    COLOR_BUTTON_PRIMARY,
    COLOR_BUTTON_PRIMARY_HOVER,
    COLOR_TEXT_LIGHT,
    COLOR_TEXT_PRIMARY,
    CONTENT_FONT,
    GRID_LINES_COLOR,
    HOVER_ROW_BG_COLOR,
    ROW_HEIGHT,
    FONT_WEIGHT_NORMAL,
    FONT_WEIGHT_SEMIBOLD,
    ICON_DELETE,
    ICON_REFRESH,
    ICON_TOTAL,
    INPUT_COLOR_BG,
    MAIN_CONTENT_BG_COLOR,
    TITLE_2_HEIGHT,
    TITLE_HEIGHT,
    UI_FONT,
    resource_path,
)


_BTN_HOVER_BG = COLOR_BUTTON_PRIMARY_HOVER


class ScheduleWorkView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {MAIN_CONTENT_BG_COLOR};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title1 = TitleBar1(
            "Sắp xếp lịch Làm việc", "assets/images/schedule_work.svg", self
        )
        self.title2 = TitleBar2(self)
        self.content = MainContent(self)

        root.addWidget(self.title1)
        root.addWidget(self.title2)
        root.addWidget(self.content, 1)


def _mk_font_normal() -> QFont:
    font_normal = QFont(UI_FONT, CONTENT_FONT)
    if FONT_WEIGHT_NORMAL >= 400:
        font_normal.setWeight(QFont.Weight.Normal)
    return font_normal


def _mk_font_semibold() -> QFont:
    font_semibold = QFont(UI_FONT, CONTENT_FONT)
    if FONT_WEIGHT_SEMIBOLD >= 500:
        font_semibold.setWeight(QFont.Weight.DemiBold)
    return font_semibold


def _mk_combo(parent: QWidget | None = None, height: int = 32) -> QComboBox:
    cb = QComboBox(parent)
    cb.setFixedHeight(height)
    cb.setFont(_mk_font_normal())
    cb.setStyleSheet(
        "\n".join(
            [
                f"QComboBox {{ border: 1px solid {COLOR_BORDER}; background: {INPUT_COLOR_BG}; padding: 0 8px; border-radius: 6px; }}",
                f"QComboBox:focus {{ border: 1px solid {COLOR_BORDER}; }}",
            ]
        )
    )
    return cb


def _mk_line_edit(parent: QWidget | None = None, height: int = 32) -> QLineEdit:
    le = QLineEdit(parent)
    le.setFixedHeight(height)
    le.setFont(_mk_font_normal())
    le.setStyleSheet(
        "\n".join(
            [
                f"QLineEdit {{ border: 1px solid {COLOR_BORDER}; background: {INPUT_COLOR_BG}; padding: 0 8px; border-radius: 6px; }}",
                f"QLineEdit:focus {{ border: 1px solid {COLOR_BORDER}; }}",
            ]
        )
    )
    return le


def _mk_date_edit(parent: QWidget | None = None, height: int = 32) -> QDateEdit:
    de = QDateEdit(parent)
    de.setFixedHeight(height)
    de.setCalendarPopup(True)
    de.setDisplayFormat("dd/MM/yyyy")
    try:
        de.setDate(QDate.currentDate())
    except Exception:
        pass
    try:
        vi_locale = QLocale(QLocale.Language.Vietnamese, QLocale.Country.Vietnam)
        de.setLocale(vi_locale)
        # Force calendar widget so navigation bar is always shown
        cal = QCalendarWidget(de)
        cal.setLocale(vi_locale)
        # Tháng/năm luôn hiển thị (không phụ thuộc hover)
        cal.setNavigationBarVisible(True)
        # Một số global QSS có thể làm chữ tháng/năm bị "mất" (màu trùng nền).
        # Set QSS cục bộ cho calendar để month/year luôn nhìn thấy.
        cal.setStyleSheet(
            "\n".join(
                [
                    f"QCalendarWidget QWidget {{ color: {COLOR_TEXT_PRIMARY}; }}",
                    f"QCalendarWidget QToolButton {{ color: {COLOR_TEXT_PRIMARY}; background: transparent; border: 0px; padding: 0 6px; }}",
                    f"QCalendarWidget QSpinBox {{ color: {COLOR_TEXT_PRIMARY}; background: {INPUT_COLOR_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 0 6px; }}",
                    f"QCalendarWidget QComboBox {{ color: {COLOR_TEXT_PRIMARY}; background: {INPUT_COLOR_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 0 6px; }}",
                    "QCalendarWidget QToolButton::menu-indicator { image: none; }",
                ]
            )
        )
        de.setCalendarWidget(cal)
    except Exception:
        pass
    de.setFont(_mk_font_normal())
    de.setStyleSheet(
        "\n".join(
            [
                f"QDateEdit {{ border: 1px solid {COLOR_BORDER}; background: {INPUT_COLOR_BG}; padding: 0 8px; border-radius: 6px; }}",
                f"QDateEdit:focus {{ border: 1px solid {COLOR_BORDER}; }}",
            ]
        )
    )
    return de


def _mk_btn_outline(
    text: str, icon_path: str | None = None, height: int = 32
) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(height)
    if icon_path:
        btn.setIcon(QIcon(resource_path(icon_path)))
        btn.setIconSize(QSize(18, 18))
    btn.setStyleSheet(
        "\n".join(
            [
                f"QPushButton {{ border: 1px solid {COLOR_BORDER}; background: transparent; padding: 0 10px; border-radius: 6px; }}",
                "QPushButton::icon { margin-right: 10px; }",
                f"QPushButton:hover {{ background: {_BTN_HOVER_BG}; color: {COLOR_TEXT_LIGHT}; }}",
            ]
        )
    )
    return btn


def _mk_btn_primary(
    text: str, icon_path: str | None = None, height: int = 32
) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(height)
    if icon_path:
        btn.setIcon(QIcon(resource_path(icon_path)))
        btn.setIconSize(QSize(18, 18))
    btn.setStyleSheet(
        "\n".join(
            [
                f"QPushButton {{ border: 1px solid {COLOR_BORDER}; background: {COLOR_BUTTON_PRIMARY}; color: {COLOR_TEXT_LIGHT}; padding: 0 12px; border-radius: 6px; }}",
                "QPushButton::icon { margin-right: 10px; }",
                f"QPushButton:hover {{ background: {COLOR_BUTTON_PRIMARY_HOVER}; color: {COLOR_TEXT_LIGHT}; }}",
            ]
        )
    )
    return btn


class TitleBar1(QWidget):
    def __init__(
        self,
        name: str = "",
        icon_svg: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TITLE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"background-color: {BG_TITLE_1_HEIGHT};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 12, 0)
        layout.setSpacing(0)

        self.icon = QLabel("")
        self.icon.setFixedSize(22, 22)
        self.icon.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        self.label = QLabel(name)
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self.label.setFont(_mk_font_normal())

        if icon_svg:
            self.set_icon(icon_svg)

        layout.addWidget(self.icon)
        layout.addSpacing(10)
        layout.addWidget(self.label, 1)

    def set_icon(self, icon_svg: str) -> None:
        icon = QIcon(resource_path(icon_svg))
        pix = icon.pixmap(QSize(22, 22))
        self.icon.setPixmap(pix)

    def set_name(self, name: str) -> None:
        self.label.setText(name or "")


class TitleBar2(QWidget):
    search_clicked = Signal()
    refresh_clicked = Signal()
    delete_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TITLE_2_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"background-color: {BG_TITLE_2_HEIGHT};")

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 0, 12, 0)
        root.setSpacing(8)

        self.cbo_search_by = _mk_combo(self, height=32)
        self.cbo_search_by.setMinimumWidth(170)
        self.cbo_search_by.addItem("Mã NV", "employee_code")
        self.cbo_search_by.addItem("Tên nhân viên", "employee_name")

        self.inp_search = _mk_line_edit(self, height=32)
        self.inp_search.setPlaceholderText("Nhập từ khóa...")
        self.inp_search.setMinimumWidth(260)

        self.btn_search = _mk_btn_primary("Tìm kiếm", None, height=32)
        self.btn_refresh = _mk_btn_outline("Làm mới", ICON_REFRESH, height=32)
        self.btn_delete = _mk_btn_outline("Xóa lịch NV", ICON_DELETE, height=32)

        self.total_icon = QLabel("")
        self.total_icon.setFixedSize(18, 18)
        self.total_icon.setPixmap(
            QIcon(resource_path(ICON_TOTAL)).pixmap(QSize(18, 18))
        )

        self.label_total = QLabel("Tổng: 0")
        self.label_total.setFont(_mk_font_normal())
        self.label_total.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )
        self.label_total.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")

        root.addWidget(self.cbo_search_by)
        root.addWidget(self.inp_search, 1)
        root.addWidget(self.btn_search)
        root.addWidget(self.btn_refresh)
        root.addWidget(self.btn_delete)
        root.addStretch(1)
        root.addWidget(self.total_icon)
        root.addWidget(self.label_total)

        try:
            self.btn_search.clicked.connect(self.search_clicked.emit)
            self.btn_refresh.clicked.connect(self.refresh_clicked.emit)
            self.btn_delete.clicked.connect(self.delete_clicked.emit)
        except Exception:
            pass

    def set_total(self, total: int | str) -> None:
        self.label_total.setText(f"Tổng: {total}")


class MainLeft(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(400)
        self.setMinimumHeight(548)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # Border-right để ngăn cách với phần nội dung bên phải
        self.setStyleSheet(
            f"background-color: {MAIN_CONTENT_BG_COLOR}; border-right: 1px solid {COLOR_BORDER};"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Cây Phòng ban/Chức danh: style giống employee_widgets.py (DepartmentTreePreview)
        self._font_normal = _mk_font_normal()
        self._font_semibold = _mk_font_semibold()
        self._dept_icon = QIcon(resource_path("assets/images/department.svg"))
        self._title_icon = QIcon(resource_path("assets/images/job_title.svg"))

        # Cache for quick lookup
        self._dept_parent_by_id: dict[int, int | None] = {}
        self._dept_name_by_id: dict[int, str] = {}

        self.tree = QTreeWidget(self)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(0)
        self.tree.setRootIsDecorated(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setIconSize(QSize(18, 18))
        try:
            self.tree.header().setStretchLastSection(True)
        except Exception:
            pass

        self.tree.setStyleSheet(
            "\n".join(
                [
                    f"QTreeWidget {{ background-color: {MAIN_CONTENT_BG_COLOR}; color: {COLOR_TEXT_PRIMARY};}}",
                    f"QTreeWidget::item {{ padding-left: 8px; padding-right: 8px; height: {ROW_HEIGHT}px; }}",
                    f"QTreeWidget::item:hover {{ background-color: {HOVER_ROW_BG_COLOR}; color: {COLOR_TEXT_PRIMARY}; }}",
                    f"QTreeWidget::item:selected {{ background-color: {HOVER_ROW_BG_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 0px; }}",
                    "QTreeWidget::item:focus { outline: none; }",
                    "QTreeWidget:focus { outline: none; }",
                ]
            )
        )

        root.addWidget(self.tree, 1)

    def set_departments(
        self,
        rows: list[tuple[int, int | None, str, str]],
        titles: list[tuple[int, int | None, str]] | None = None,
    ) -> None:
        self.tree.clear()
        titles = titles or []

        # Build lookup maps for parent/name
        self._dept_parent_by_id.clear()
        self._dept_name_by_id.clear()
        for dept_id, parent_id, name, _note in rows or []:
            try:
                did = int(dept_id)
            except Exception:
                continue
            pid = int(parent_id) if parent_id is not None else None
            self._dept_parent_by_id[did] = pid
            self._dept_name_by_id[did] = str(name or "").strip()

        by_parent: dict[int | None, list[tuple[int, int | None, str]]] = defaultdict(
            list
        )
        for dept_id, parent_id, name, _note in rows or []:
            dept_id_i = int(dept_id)
            parent_id_i = int(parent_id) if parent_id is not None else None
            by_parent[parent_id_i].append((dept_id_i, parent_id_i, name or ""))

        for k in list(by_parent.keys()):
            by_parent[k].sort(key=lambda x: x[0])

        titles_by_department: dict[int | None, list[tuple[int, str]]] = defaultdict(
            list
        )
        for title_id, department_id, title_name in titles or []:
            try:
                tid = int(title_id)
            except Exception:
                continue
            did = int(department_id) if department_id is not None else None
            titles_by_department[did].append((tid, str(title_name or "").strip()))

        for k in list(titles_by_department.keys()):
            titles_by_department[k].sort(key=lambda x: x[0])

        def build(
            parent_item: QTreeWidgetItem | None,
            parent_id: int | None,
            prefix_parts: list[str],
        ) -> None:
            dept_children = by_parent.get(parent_id, [])
            title_children = titles_by_department.get(parent_id, [])

            combined: list[tuple[str, int, str]] = []
            combined.extend(
                [("dept", d_id, d_name) for (d_id, _p, d_name) in dept_children]
            )
            combined.extend(
                [("title", t_id, t_name) for (t_id, t_name) in title_children]
            )

            for idx, (node_type, node_id, name) in enumerate(combined):
                is_last = idx == (len(combined) - 1)
                connector = "└── " if is_last else "├── "

                prefix = "".join(prefix_parts) + connector
                display_name = f"{prefix}{name}"

                item = QTreeWidgetItem([display_name])
                item.setFont(0, self._font_normal)
                item.setIcon(
                    0, self._dept_icon if node_type == "dept" else self._title_icon
                )
                item.setData(0, Qt.ItemDataRole.UserRole, int(node_id))
                item.setData(0, Qt.ItemDataRole.UserRole + 1, name or "")
                item.setData(0, Qt.ItemDataRole.UserRole + 2, node_type)
                item.setData(0, Qt.ItemDataRole.UserRole + 3, parent_id)

                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)

                next_prefix_parts = list(prefix_parts)
                if prefix_parts:
                    next_prefix_parts.append("    " if is_last else "│   ")
                else:
                    next_prefix_parts = ["    " if is_last else "│   "]

                if node_type == "dept":
                    build(item, int(node_id), next_prefix_parts)

        build(None, None, [])
        self.tree.expandAll()

    def get_selected_node_context(self) -> dict | None:
        item = self.tree.currentItem()
        if item is None:
            return None

        try:
            node_id = int(item.data(0, Qt.ItemDataRole.UserRole) or 0)
        except Exception:
            return None
        if node_id <= 0:
            return None

        name = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "").strip()
        node_type = str(item.data(0, Qt.ItemDataRole.UserRole + 2) or "dept")
        if node_type not in ("dept", "title"):
            node_type = "dept"

        parent_id = item.data(0, Qt.ItemDataRole.UserRole + 3)
        try:
            parent_id_i = int(parent_id) if parent_id is not None else None
        except Exception:
            parent_id_i = None

        if node_type == "dept":
            return {
                "type": "dept",
                "id": int(node_id),
                "name": name,
                "parent_id": parent_id_i,
            }

        # title node: parent_id field stores department_id
        return {
            "type": "title",
            "id": int(node_id),
            "name": name,
            "department_id": parent_id_i,
        }


class MainRight(QWidget):
    DISPLAY_NAME = "Lịch trình mặc định"
    COL_CHECK = 0
    COL_ID = 1
    COL_EMP_CODE = 2
    COL_MCC_CODE = 3
    COL_FULL_NAME = 4
    COL_DEPARTMENT = 5
    COL_TITLE = 6
    COL_SCHEDULE = 7

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Tên section (dùng cho debug/nhận diện và có thể target trong QSS)
        self.display_name = self.DISPLAY_NAME
        try:
            self.setObjectName("mainRight_default_schedule")
        except Exception:
            pass
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setMinimumWidth(1200)
        self.setMinimumHeight(254)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {MAIN_CONTENT_BG_COLOR};")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Title của panel bên phải
        self.lbl_panel_title = QLabel(self.DISPLAY_NAME)
        self.lbl_panel_title.setFont(_mk_font_semibold())
        self.lbl_panel_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")

        # Header (trái→phải): label, combobox, button
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        self.lbl_schedule = QLabel("Lịch làm việc")
        self.lbl_schedule.setFont(_mk_font_normal())
        self.lbl_schedule.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")

        self.cbo_schedule = _mk_combo(self, height=32)
        self.cbo_schedule.setFixedWidth(300)

        self.btn_apply = _mk_btn_primary("Áp dụng", None, height=32)
        self.btn_apply.setFixedWidth(100)

        header.addWidget(self.lbl_schedule)
        header.addWidget(self.cbo_schedule)
        header.addWidget(self.btn_apply)
        header.addStretch(1)

        # Bảng nhân viên
        self.table = QTableWidget(self)
        self.table.setRowCount(0)
        self.table.setColumnCount(8)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        try:
            # Không hiển thị cột số thứ tự bên trái
            self.table.verticalHeader().setVisible(False)
        except Exception:
            pass

        # Match EmployeeTable row sizing
        try:
            self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
            self.table.verticalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Fixed
            )
        except Exception:
            pass

        self.table.setHorizontalHeaderLabels(
            [
                "",
                "ID",
                "Mã NV",
                "Mã CC",
                "Tên NV",
                "Phòng ban",
                "Chức danh",
                "Lịch làm việc",
            ]
        )

        try:
            hh = self.table.horizontalHeader()
            hh.setStretchLastSection(True)
            hh.setFixedHeight(ROW_HEIGHT)
            hh.setMinimumSectionSize(80)

            # Auto fit table width (W)
            hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(self.COL_CHECK, QHeaderView.ResizeMode.Fixed)
            hh.setSectionResizeMode(self.COL_ID, QHeaderView.ResizeMode.Fixed)
        except Exception:
            pass

        try:
            self.table.setColumnWidth(self.COL_CHECK, 40)
            self.table.setColumnWidth(self.COL_ID, 40)
            self.table.setColumnWidth(self.COL_EMP_CODE, 130)
            self.table.setColumnWidth(self.COL_MCC_CODE, 130)
            self.table.setColumnWidth(self.COL_FULL_NAME, 240)
            self.table.setColumnWidth(self.COL_DEPARTMENT, 170)
            self.table.setColumnWidth(self.COL_TITLE, 160)
            self.table.setColumnWidth(self.COL_SCHEDULE, 240)
        except Exception:
            pass

        # Hide ID column per requirement
        try:
            self.table.setColumnHidden(self.COL_ID, True)
        except Exception:
            pass

        self.table.setStyleSheet(
            "\n".join(
                [
                    f"QTableWidget {{ background-color: {MAIN_CONTENT_BG_COLOR}; gridline-color: {GRID_LINES_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; }}",
                    f"QHeaderView::section {{ background-color: {BG_TITLE_2_HEIGHT}; color: {COLOR_TEXT_PRIMARY}; border-top: 1px solid {GRID_LINES_COLOR}; border-bottom: 1px solid {GRID_LINES_COLOR}; border-left: 0px; border-right: 1px solid {GRID_LINES_COLOR}; height: {ROW_HEIGHT}px; }}",
                    f"QTableWidget::item:hover {{ background-color: {HOVER_ROW_BG_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 0px; border-radius: 0px; }}",
                    f"QTableWidget::item:selected {{ background-color: {HOVER_ROW_BG_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 0px; border-radius: 0px; }}",
                    "QTableWidget::item:focus { outline: none; }",
                    "QTableWidget:focus { outline: none; }",
                ]
            )
        )
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        try:
            self.table.cellClicked.connect(self._on_cell_clicked)
        except Exception:
            pass

        try:
            self.cbo_schedule.currentIndexChanged.connect(self._update_schedule_label)
        except Exception:
            pass

        # Line separator: ngăn cách nội dung header với bảng
        self.sep_header_table = QFrame(self)
        self.sep_header_table.setFrameShape(QFrame.Shape.HLine)
        self.sep_header_table.setFixedHeight(1)
        self.sep_header_table.setStyleSheet(f"background-color: {COLOR_BORDER};")

        root.addWidget(self.lbl_panel_title)
        root.addLayout(header)
        root.addWidget(self.sep_header_table)
        root.addWidget(self.table, 1)

        # Init label text based on current selection
        try:
            self._update_schedule_label()
        except Exception:
            pass

    def _update_schedule_label(self) -> None:
        try:
            name = str(self.cbo_schedule.currentText() or "").strip()
            data = self.cbo_schedule.currentData()
        except Exception:
            self.lbl_schedule.setText("Lịch làm việc")
            return

        # Placeholder
        if data is None:
            self.lbl_schedule.setText("Lịch làm việc")
            return

        # Clear option
        if str(data) == "0":
            self.lbl_schedule.setText("Lịch làm việc: Chưa sắp xếp ca")
            return

        # Selected schedule
        if name and not name.startswith("--"):
            self.lbl_schedule.setText(f"Lịch làm việc: {name}")
        else:
            self.lbl_schedule.setText("Lịch làm việc")

    def set_schedules(self, items: list[tuple[int, str]]) -> None:
        self.cbo_schedule.clear()
        # Index 0: placeholder (không áp dụng)
        self.cbo_schedule.addItem("-- Chọn lịch làm việc --", None)
        # Index 1: clear schedule assignment
        self.cbo_schedule.addItem("Chưa sắp xếp ca", 0)
        for sid, name in items or []:
            try:
                self.cbo_schedule.addItem(str(name or ""), int(sid))
            except Exception:
                continue

    def apply_schedule_name_map(self, schedule_by_employee_id: dict[int, str]) -> None:
        if not schedule_by_employee_id:
            return

        for r in range(self.table.rowCount()):
            it_id = self.table.item(r, self.COL_ID)
            if it_id is None:
                continue
            raw = str(it_id.text() or "").strip()
            if not raw:
                continue
            try:
                emp_id = int(raw)
            except Exception:
                continue

            schedule_name = str(schedule_by_employee_id.get(emp_id) or "").strip()
            it_sched = self.table.item(r, self.COL_SCHEDULE)
            if it_sched is None:
                it_sched = QTableWidgetItem("")
                it_sched.setFlags(
                    Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                )
                self.table.setItem(r, self.COL_SCHEDULE, it_sched)
            it_sched.setText(schedule_name)

    def clear_employees(self) -> None:
        self.table.setRowCount(0)

    def set_employees(self, rows: list[dict] | list[object]) -> None:
        """Accept list of dataclass-like objects or dicts.

        Expected fields:
        - id, employee_code, mcc_code, full_name
        """

        self.table.setRowCount(0)
        if not rows:
            return

        # Sắp xếp theo ID tăng dần để ra thứ tự 1,2,3..n ổn định
        def _key(x) -> int:
            try:
                if isinstance(x, dict):
                    return int(x.get("id") or 0)
                return int(getattr(x, "id", None) or 0)
            except Exception:
                return 0

        sorted_rows = sorted(list(rows), key=_key)

        self.table.setRowCount(len(sorted_rows))
        for r, item in enumerate(sorted_rows):

            def _get(key: str, default=""):
                if isinstance(item, dict):
                    return item.get(key, default)
                return getattr(item, key, default)

            emp_id = _get("id")
            emp_code = _get("employee_code")
            mcc_code = _get("mcc_code")
            full_name = _get("full_name")
            department_name = _get("department_name", "")
            title_name = _get("title_name", "")
            schedule_name = _get("schedule_name", "")

            # Checkbox column: default ❌ (toggle to ✅ by click)
            chk = QTableWidgetItem("❌")
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            try:
                # Làm biểu tượng ✅/❌ to hơn để dễ nhìn
                f = QFont(UI_FONT, int(CONTENT_FONT) + 4)
                chk.setFont(f)
            except Exception:
                pass
            chk.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_CHECK, chk)

            it_id = QTableWidgetItem(str(emp_id if emp_id is not None else ""))
            it_id.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_ID, it_id)

            it_code = QTableWidgetItem(str(emp_code or ""))
            it_code.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_EMP_CODE, it_code)

            it_mcc = QTableWidgetItem(str(mcc_code or ""))
            it_mcc.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_MCC_CODE, it_mcc)

            it_name = QTableWidgetItem(str(full_name or ""))
            it_name.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_FULL_NAME, it_name)

            it_dept = QTableWidgetItem(str(department_name or ""))
            it_dept.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_DEPARTMENT, it_dept)

            it_title = QTableWidgetItem(str(title_name or ""))
            it_title.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_TITLE, it_title)

            it_sched = QTableWidgetItem("")
            it_sched.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, self.COL_SCHEDULE, it_sched)
            try:
                it_sched.setText(str(schedule_name or "").strip())
            except Exception:
                pass

            try:
                self.table.setRowHeight(r, ROW_HEIGHT)
            except Exception:
                pass

    def get_checked_employee_ids(self) -> list[int]:
        ids: list[int] = []
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, self.COL_CHECK)
            if chk is None or chk.text() != "✅":
                continue
            it_id = self.table.item(r, self.COL_ID)
            if it_id is None:
                continue
            raw = str(it_id.text() or "").strip()
            if not raw:
                continue
            try:
                ids.append(int(raw))
            except Exception:
                continue
        return ids

    def apply_schedule_to_checked(self, schedule_name: str) -> int:
        applied = 0
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, self.COL_CHECK)
            if chk is None or chk.text() != "✅":
                continue
            it_sched = self.table.item(r, self.COL_SCHEDULE)
            if it_sched is None:
                it_sched = QTableWidgetItem("")
                it_sched.setFlags(
                    Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                )
                self.table.setItem(r, self.COL_SCHEDULE, it_sched)
            it_sched.setText(str(schedule_name or "").strip())
            applied += 1
        return applied

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col != self.COL_CHECK:
            return
        it = self.table.item(row, col)
        if it is None:
            return
        it.setText("✅" if it.text() != "✅" else "❌")


class TempScheduleContent(QWidget):
    add_clicked = Signal()
    delete_clicked = Signal()

    COL_ID = 0
    COL_EMP_CODE = 1
    COL_FULL_NAME = 2
    COL_FROM_DATE = 3
    COL_TO_DATE = 4
    COL_SCHEDULE = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {MAIN_CONTENT_BG_COLOR};")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self.lbl_title = QLabel("Lịch trình tạm")
        self.lbl_title.setFont(_mk_font_semibold())
        self.lbl_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        # Left controls
        self.left = QWidget(self)
        self.left.setFixedWidth(400)
        self.left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.left.setStyleSheet(f"background-color: {MAIN_CONTENT_BG_COLOR};")

        left_root = QVBoxLayout(self.left)
        left_root.setContentsMargins(0, 0, 0, 0)
        left_root.setSpacing(8)

        self.lbl_from = QLabel("Từ ngày")
        self.lbl_from.setFont(_mk_font_normal())
        self.lbl_from.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")
        self.inp_from = _mk_date_edit(self.left, height=32)

        self.lbl_to = QLabel("Đến ngày")
        self.lbl_to.setFont(_mk_font_normal())
        self.lbl_to.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")
        self.inp_to = _mk_date_edit(self.left, height=32)

        self.lbl_schedule = QLabel("Lịch làm việc")
        self.lbl_schedule.setFont(_mk_font_normal())
        self.lbl_schedule.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};")
        self.cbo_schedule = _mk_combo(self.left, height=32)
        self.cbo_schedule.setFixedWidth(300)

        # Toggle dạng ❌/✅ (thay thế QCheckBox mặc định)
        self.chk_update_by_selected = QPushButton("❌ Cập nhập theo nhân viên chọn")
        self.chk_update_by_selected.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_update_by_selected.setCheckable(True)
        self.chk_update_by_selected.setChecked(False)
        self.chk_update_by_selected.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_update_by_selected.setFont(_mk_font_normal())
        self.chk_update_by_selected.setStyleSheet(
            "\n".join(
                [
                    "QPushButton { border: 0px; background: transparent; text-align: left; padding: 0px; }",
                    f"QPushButton {{ color: {COLOR_TEXT_PRIMARY}; }}",
                ]
            )
        )

        def _sync_update_by_selected_text() -> None:
            prefix = "✅" if bool(self.chk_update_by_selected.isChecked()) else "❌"
            self.chk_update_by_selected.setText(
                f"{prefix} Cập nhập theo nhân viên chọn"
            )

        try:
            self.chk_update_by_selected.toggled.connect(_sync_update_by_selected_text)
        except Exception:
            pass
        _sync_update_by_selected_text()

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)

        self.btn_add = _mk_btn_primary("Thêm mới", None, height=32)
        self.btn_add.setFixedWidth(120)
        self.btn_delete = _mk_btn_outline("Xóa bỏ", ICON_DELETE, height=32)
        self.btn_delete.setFixedWidth(120)

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch(1)

        left_root.addWidget(self.lbl_from)
        left_root.addWidget(self.inp_from)
        left_root.addWidget(self.lbl_to)
        left_root.addWidget(self.inp_to)
        left_root.addWidget(self.lbl_schedule)
        left_root.addWidget(self.cbo_schedule)
        left_root.addWidget(self.chk_update_by_selected)
        left_root.addLayout(btn_row)
        left_root.addStretch(1)

        # Right table
        self.table = QTableWidget(self)
        self.table.setRowCount(0)
        self.table.setColumnCount(6)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Mã NV",
                "Tên Nhân viên",
                "Từ ngày",
                "Đến ngày",
                "Lịch làm việc",
            ]
        )

        try:
            hh = self.table.horizontalHeader()
            hh.setStretchLastSection(True)
            hh.setFixedHeight(ROW_HEIGHT)
            hh.setMinimumSectionSize(80)

            # Auto fit table width (W)
            hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass

        try:
            self.table.setColumnWidth(self.COL_ID, 60)
            self.table.setColumnWidth(self.COL_EMP_CODE, 120)
            self.table.setColumnWidth(self.COL_FULL_NAME, 220)
            self.table.setColumnWidth(self.COL_FROM_DATE, 110)
            self.table.setColumnWidth(self.COL_TO_DATE, 110)
            self.table.setColumnWidth(self.COL_SCHEDULE, 220)
        except Exception:
            pass

        try:
            self.table.verticalHeader().setVisible(False)
            self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
            self.table.verticalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Fixed
            )
        except Exception:
            pass

        # Hide ID column (giữ dữ liệu, chỉ ẩn hiển thị)
        try:
            self.table.setColumnHidden(self.COL_ID, True)
        except Exception:
            pass

        self.table.setStyleSheet(
            "\n".join(
                [
                    f"QTableWidget {{ background-color: {MAIN_CONTENT_BG_COLOR}; gridline-color: {GRID_LINES_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; }}",
                    f"QHeaderView::section {{ background-color: {BG_TITLE_2_HEIGHT}; color: {COLOR_TEXT_PRIMARY}; border-top: 1px solid {GRID_LINES_COLOR}; border-bottom: 1px solid {GRID_LINES_COLOR}; border-left: 0px; border-right: 1px solid {GRID_LINES_COLOR}; height: {ROW_HEIGHT}px; }}",
                    f"QTableWidget::item:hover {{ background-color: {HOVER_ROW_BG_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 0px; border-radius: 0px; }}",
                    f"QTableWidget::item:selected {{ background-color: {HOVER_ROW_BG_COLOR}; color: {COLOR_TEXT_PRIMARY}; border: 0px; border-radius: 0px; }}",
                    "QTableWidget::item:focus { outline: none; }",
                    "QTableWidget:focus { outline: none; }",
                ]
            )
        )

        # Vertical separator: ngăn cách phần nhập liệu (trái) với bảng (phải)
        self.sep_left_table = QFrame(self)
        self.sep_left_table.setFrameShape(QFrame.Shape.VLine)
        self.sep_left_table.setFixedWidth(1)
        self.sep_left_table.setStyleSheet(f"background-color: {COLOR_BORDER};")

        row.addWidget(self.left)
        row.addWidget(self.sep_left_table)
        row.addWidget(self.table, 1)

        root.addWidget(self.lbl_title)
        root.addLayout(row)

        try:
            self.btn_add.clicked.connect(self.add_clicked.emit)
            self.btn_delete.clicked.connect(self.delete_clicked.emit)
        except Exception:
            pass

    def clear_rows(self) -> None:
        self.table.setRowCount(0)

    def set_schedules(self, items: list[tuple[int, str]]) -> None:
        self.cbo_schedule.clear()
        self.cbo_schedule.addItem("-- Chọn lịch làm việc --", None)
        self.cbo_schedule.addItem("Chưa sắp xếp ca", 0)
        for sid, name in items or []:
            try:
                self.cbo_schedule.addItem(str(name or ""), int(sid))
            except Exception:
                continue


class MainContent(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {MAIN_CONTENT_BG_COLOR};")
        self.setMinimumHeight(254)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left panel occupies full height
        self.left = MainLeft(self)

        # Right side stacks panels vertically
        right_container = QWidget(self)
        right_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        right_container.setStyleSheet(f"background-color: {MAIN_CONTENT_BG_COLOR};")

        right_root = QVBoxLayout(right_container)
        right_root.setContentsMargins(0, 0, 0, 0)
        right_root.setSpacing(0)

        self.right = MainRight(right_container)
        self.temp = TempScheduleContent(right_container)

        # Separator between 2 panels bên phải (MainRight và Lịch trình tạm)
        sep_panels = QFrame(right_container)
        sep_panels.setFrameShape(QFrame.Shape.HLine)
        sep_panels.setFixedHeight(1)
        sep_panels.setStyleSheet(f"background-color: {COLOR_BORDER};")

        right_root.addWidget(self.right, 2)
        right_root.addWidget(sep_panels)
        right_root.addWidget(self.temp, 1)

        root.addWidget(self.left)
        root.addWidget(right_container, 1)
