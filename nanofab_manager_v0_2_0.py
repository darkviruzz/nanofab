from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFontMetrics, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpacerItem,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from nanofab_modular import ProcessEngine, build_default_modules
from nanofab_modular.domain import ArtifactRef, ProcStatus, SampleState
from nanofab_modular.engine import StepRuntime
from nanofab_modular.step_api import ParamType, ProcessStepModule, StepParamSpec, ValidationIssue

APP_NAME = "NanoFab Manager"
APP_VERSION = "0.2.0"


def _is_dark_palette(palette: QPalette) -> bool:
    return palette.color(QPalette.Window).lightness() < 128


def _card_frame_style() -> str:
    return "QFrame { background: palette(base); border: 1px solid palette(mid); border-radius: 14px; }"


def _muted_text_style() -> str:
    return "color: palette(text);"


def _warning_box_style(palette: QPalette) -> str:
    _ = palette
    return "padding: 10px; border-radius: 10px; background: palette(alternate-base); border: 1px solid palette(mid); color: palette(text);"


def _ok_box_style(palette: QPalette) -> str:
    _ = palette
    return "padding: 10px; border-radius: 10px; background: palette(base); border: 1px solid palette(mid); color: palette(text);"


def _status_color(status: ProcStatus) -> QColor:
    app = QApplication.instance()
    palette = app.palette() if app is not None else QPalette()
    if _is_dark_palette(palette):
        if status == ProcStatus.DONE:
            return QColor("#66d17a")
        if status == ProcStatus.READY:
            return QColor("#f0c674")
        if status == ProcStatus.RUNNING:
            return QColor("#64b5f6")
        if status == ProcStatus.WARNING:
            return QColor("#ffcc80")
        if status in (ProcStatus.BLOCKED, ProcStatus.FAILED, ProcStatus.ABORTED):
            return QColor("#ff7b72")
        return palette.color(QPalette.Text)

    if status == ProcStatus.DONE:
        return QColor("#0f7b0f")
    if status == ProcStatus.READY:
        return QColor("#8a6d00")
    if status == ProcStatus.RUNNING:
        return QColor("#1565c0")
    if status == ProcStatus.WARNING:
        return QColor("#a86000")
    if status in (ProcStatus.BLOCKED, ProcStatus.FAILED, ProcStatus.ABORTED):
        return QColor("#b00020")
    return QColor("#555555")


def _icon_from_theme_or_fallback(theme_name: str, fallback_color: QColor) -> QIcon:
    icon = QIcon.fromTheme(theme_name)
    if not icon.isNull():
        return icon
    pix = QPixmap(64, 64)
    pix.fill(fallback_color)
    return QIcon(pix)


class ProcessTableModel(QAbstractTableModel):
    COL_STEP = 0
    COL_PROCESS = 1
    COL_PARAMS = 2
    COL_STATUS = 3

    headers = ["Step", "Process", "Parameters", "Status"]

    def __init__(self, engine: ProcessEngine) -> None:
        super().__init__()
        self.engine = engine

    def _rows(self) -> list[StepRuntime]:
        return self.engine.steps_in_order()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows())

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else 4

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.headers[section]
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        runtime = self._rows()[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == self.COL_STEP:
                return str(runtime.order)
            if col == self.COL_PROCESS:
                return runtime.module.display_name
            if col == self.COL_PARAMS:
                return runtime.key_params
            if col == self.COL_STATUS:
                return runtime.status.value

        if role == Qt.UserRole and col == self.COL_STEP:
            return runtime.order

        if role == Qt.TextAlignmentRole:
            if col == self.COL_STEP:
                return int(Qt.AlignCenter)
            return int(Qt.AlignVCenter | Qt.AlignLeft)

        if role == Qt.ForegroundRole and col == self.COL_STATUS:
            return _status_color(runtime.status)

        return None

    def runtime_at(self, row: int) -> StepRuntime:
        rows = self._rows()
        if row < 0 or row >= len(rows):
            raise IndexError(f"Row out of range: {row}")
        return rows[row]

    def row_for_step(self, step_id: str) -> int | None:
        for idx, runtime in enumerate(self._rows()):
            if runtime.module.step_id == step_id:
                return idx
        return None

    def step_id_at(self, row: int) -> str:
        return self.runtime_at(row).module.step_id

    @staticmethod
    def _is_done_like(status: ProcStatus) -> bool:
        return status in (ProcStatus.DONE, ProcStatus.WARNING)

    def first_unfinished_row(self) -> int | None:
        for idx, runtime in enumerate(self._rows()):
            if not self._is_done_like(runtime.status):
                return idx
        return None

    def is_row_movable(self, row: int) -> bool:
        if row < 0 or row >= self.rowCount():
            return False
        first = self.first_unfinished_row()
        if first is None:
            return False
        runtime = self.runtime_at(row)
        if runtime.status == ProcStatus.RUNNING:
            return False
        return row >= first

    def action_label_for_row(self, row: int) -> str:
        runtime = self.runtime_at(row)
        if runtime.status == ProcStatus.RUNNING:
            return "Running"
        if self._is_done_like(runtime.status):
            return "Done"
        first = self.first_unfinished_row()
        if first is None:
            return "Done"
        return "Run Now" if row == first else "Pending"

    def move_row(self, source_row: int, target_row: int) -> bool:
        if source_row == target_row:
            return True
        if not self.is_row_movable(source_row):
            return False
        first = self.first_unfinished_row()
        if first is None:
            return False
        if target_row < first:
            return False
        if target_row >= self.rowCount():
            target_row = self.rowCount() - 1
        if target_row < 0:
            return False
        step_id = self.runtime_at(source_row).module.step_id
        moved = self.engine.move_step(step_id, target_row)
        if moved:
            self.refresh()
        return moved

    def move_step_id(self, step_id: str, target_row: int) -> bool:
        source_row = self.row_for_step(step_id)
        if source_row is None:
            return False
        return self.move_row(source_row, target_row)

    def refresh(self) -> None:
        total_rows = self.rowCount()
        total_cols = self.columnCount()
        if total_rows <= 0 or total_cols <= 0:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(total_rows - 1, total_cols - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.ForegroundRole, Qt.UserRole])


class StatusFilterProxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)
        self.setSortRole(Qt.UserRole)
        self._status_value: str = "All"

    def set_status_filter(self, status_value: str) -> None:
        self._status_value = status_value
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if self.filterRegularExpression().pattern():
            rx = self.filterRegularExpression()
            model = self.sourceModel()
            assert model is not None
            matched = False
            for col in (ProcessTableModel.COL_PROCESS, ProcessTableModel.COL_PARAMS):
                idx = model.index(source_row, col, source_parent)
                text = str(model.data(idx, Qt.DisplayRole) or "")
                if rx.match(text).hasMatch():
                    matched = True
                    break
            if not matched:
                return False

        if self._status_value == "All":
            return True

        model = self.sourceModel()
        assert model is not None
        idx = model.index(source_row, ProcessTableModel.COL_STATUS, source_parent)
        status_text = str(model.data(idx, Qt.DisplayRole) or "")
        return status_text == self._status_value


class MainView(QWidget):
    open_process_requested = Signal(int)
    run_process_requested = Signal(int)

    def __init__(self, model: ProcessTableModel, proxy: QSortFilterProxyModel) -> None:
        super().__init__()
        self.model = model
        self.proxy = proxy

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(10)

        filter_bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search processes...")
        self.search.textChanged.connect(self._apply_filters)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["All"] + [s.value for s in ProcStatus])
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        filter_bar.addWidget(self.search, 3)
        filter_bar.addWidget(self.status_filter, 1)

        split = QHBoxLayout()
        split.setSpacing(14)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setSortingEnabled(False)
        self.table.doubleClicked.connect(self._open_selected)
        self.table.setAlternatingRowColors(True)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setColumnWidth(ProcessTableModel.COL_STEP, 60)
        self.table.setColumnWidth(ProcessTableModel.COL_PROCESS, 300)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.context = QWidget()
        ctx_layout = QVBoxLayout(self.context)
        ctx_layout.setContentsMargins(12, 12, 12, 12)
        ctx_layout.setSpacing(10)

        self.ctx_title = QLabel("Select a process")
        self.ctx_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.ctx_status = QLabel("")
        self.ctx_summary = QLabel("")
        self.ctx_summary.setWordWrap(True)
        self.ctx_blocked = QLabel("")
        self.ctx_blocked.setWordWrap(True)
        self.ctx_blocked.hide()
        self.ctx_warning = QLabel("")
        self.ctx_warning.setWordWrap(True)
        self.ctx_warning.hide()

        self.ctx_io = QLabel("")
        self.ctx_io.setWordWrap(True)
        self.ctx_artifact = QLabel("Last artifact: -")
        self.ctx_artifact.setWordWrap(True)

        btn_row = QHBoxLayout()
        self.btn_open = QPushButton("Open Parameters")
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_run = QPushButton("Run Step")
        self.btn_run.clicked.connect(self._run_selected)
        self.btn_artifacts = QPushButton("Open Artifacts")
        self.btn_artifacts.clicked.connect(self._mock_open_artifacts)

        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_artifacts)

        ctx_layout.addWidget(self.ctx_title)
        ctx_layout.addWidget(self.ctx_status)
        ctx_layout.addWidget(self.ctx_summary)
        ctx_layout.addWidget(self.ctx_blocked)
        ctx_layout.addWidget(self.ctx_warning)
        ctx_layout.addWidget(self.ctx_io)
        ctx_layout.addWidget(self.ctx_artifact)
        ctx_layout.addLayout(btn_row)
        ctx_layout.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.ctx_frame = QFrame()
        ctx_frame_layout = QVBoxLayout(self.ctx_frame)
        ctx_frame_layout.setContentsMargins(0, 0, 0, 0)
        ctx_frame_layout.addWidget(self.context)

        split.addWidget(self.table, 7)
        split.addWidget(self.ctx_frame, 3)

        root.addLayout(filter_bar)
        root.addLayout(split)

        sel_model = self.table.selectionModel()
        sel_model.selectionChanged.connect(self._update_context_from_selection)

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        palette = self.palette()
        self.ctx_frame.setStyleSheet(_card_frame_style())
        self.ctx_blocked.setStyleSheet(_warning_box_style(palette))
        self.ctx_warning.setStyleSheet(_warning_box_style(palette))
        self.ctx_io.setStyleSheet(_muted_text_style())
        self.ctx_artifact.setStyleSheet(_muted_text_style())

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.PaletteChange:
            self._apply_theme_styles()
        super().changeEvent(event)

    def _apply_filters(self) -> None:
        text = self.search.text().strip()
        self.proxy.setFilterFixedString(text)
        self.proxy.invalidateFilter()

    def _selected_source_row(self) -> int | None:
        sel = self.table.selectionModel()
        if sel is None or not sel.hasSelection():
            return None
        selected_rows = sel.selectedRows()
        if not selected_rows:
            return None
        proxy_index = selected_rows[0]
        if not proxy_index.isValid():
            return None
        source_index = self.proxy.mapToSource(proxy_index)
        if not source_index.isValid():
            return None
        row = source_index.row()
        if row < 0 or row >= self.model.rowCount():
            return None
        return row

    def _open_selected(self) -> None:
        row = self._selected_source_row()
        if row is None:
            return
        self.open_process_requested.emit(row)

    def _run_selected(self) -> None:
        row = self._selected_source_row()
        if row is None:
            return
        self.run_process_requested.emit(row)

    def _update_context_from_selection(self) -> None:
        row = self._selected_source_row()
        if row is None:
            self.ctx_title.setText("Select a process")
            self.ctx_status.setText("")
            self.ctx_summary.setText("")
            self.ctx_io.setText("")
            self.ctx_artifact.setText("Last artifact: -")
            self.ctx_blocked.hide()
            self.ctx_warning.hide()
            return

        try:
            runtime = self.model.runtime_at(row)
        except IndexError:
            self.ctx_title.setText("Select a process")
            self.ctx_status.setText("")
            self.ctx_summary.setText("")
            self.ctx_io.setText("")
            self.ctx_artifact.setText("Last artifact: -")
            self.ctx_blocked.hide()
            self.ctx_warning.hide()
            return
        self.ctx_title.setText(runtime.module.display_name)
        self.ctx_status.setText(f"Status: {runtime.status.value}")
        self.ctx_summary.setText(runtime.notes or runtime.module.description)
        self.ctx_artifact.setText(f"Last artifact: {runtime.last_artifact or '-'}")

        if runtime.status == ProcStatus.BLOCKED and runtime.blocked_reason:
            self.ctx_blocked.setText(runtime.blocked_reason)
            self.ctx_blocked.show()
        else:
            self.ctx_blocked.hide()

        if runtime.last_warning:
            self.ctx_warning.setText(runtime.last_warning)
            self.ctx_warning.show()
        else:
            self.ctx_warning.hide()

        in_text = "; ".join(runtime.module.input_descriptions())
        out_text = "; ".join(runtime.module.output_descriptions())
        self.ctx_io.setText(f"Inputs: {in_text}\nOutputs: {out_text}")

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.InsertParagraphSeparator) or event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._open_selected()
            return
        super().keyPressEvent(event)

    def _mock_open_artifacts(self) -> None:
        row = self._selected_source_row()
        if row is None:
            QMessageBox.information(self, "Artifacts", "Select a process first.")
            return
        runtime = self.model.runtime_at(row)
        QMessageBox.information(self, "Artifacts", runtime.last_artifact or "No artifact yet for this step.")

    def refresh_context(self) -> None:
        self._update_context_from_selection()


class RecipeCardView(QWidget):
    back_requested = Signal()
    saved = Signal(int)
    run_requested = Signal(int)

    def __init__(self, engine: ProcessEngine, model: ProcessTableModel) -> None:
        super().__init__()
        self.setObjectName("DetailsCard")
        self.engine = engine
        self.model = model
        self._current_row: int | None = None
        self._current_step_id: str | None = None
        self._run_action_text: str = "Pending"
        self._inputs_locked: bool = False
        self._original_params: dict[str, Any] = {}
        self._field_specs: list[StepParamSpec] = []
        self._widgets: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("Process Parameters")
        self.title.setObjectName("DetailsTitle")
        header.addWidget(self.title)
        header.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.btn_back = QPushButton("Back to Chain")
        self.btn_back.setObjectName("BackLink")
        self.btn_back.clicked.connect(self.back_requested.emit)
        self.btn_validate = QPushButton("Validate")
        self.btn_validate.setObjectName("SecondaryActionButton")
        self.btn_validate.clicked.connect(self._validate_clicked)
        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("SecondaryActionButton")
        self.btn_save.clicked.connect(self._save_clicked)
        self.btn_revert = QPushButton("Revert")
        self.btn_revert.setObjectName("SecondaryActionButton")
        self.btn_revert.clicked.connect(self._revert_clicked)
        self.btn_run = QPushButton("Pending")
        self.btn_run.setObjectName("RowActionButton")
        self.btn_run.setMinimumWidth(100)
        self.btn_run.clicked.connect(self._run_clicked)

        header.addWidget(self.btn_back)
        header.addWidget(self.btn_validate)
        header.addWidget(self.btn_save)
        header.addWidget(self.btn_revert)
        header.addWidget(self.btn_run)
        root.addLayout(header)

        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body_host = QWidget()
        body = QVBoxLayout(body_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        self.form_frame = QFrame()
        self.form_frame.setObjectName("PanelCard")
        form_layout = QVBoxLayout(self.form_frame)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setSpacing(10)

        self.subtitle = QLabel("Step metadata")
        self.subtitle.setObjectName("DetailsSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.subtitle.setStyleSheet("padding: 8px 10px; border-radius: 10px;")
        self.meta_line = QLabel("")
        self.meta_line.setObjectName("MutedText")
        self.meta_line.setWordWrap(False)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setFormAlignment(Qt.AlignTop)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(10)

        form_layout.addWidget(self.subtitle)
        form_layout.addWidget(self.meta_line)
        form_layout.addLayout(self.form)
        form_layout.addStretch(1)

        self.side_frame = QFrame()
        self.side_frame.setObjectName("PanelCard")
        side_layout = QVBoxLayout(self.side_frame)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(10)

        self.validation_title = QLabel("Validation")
        self.validation_title.setObjectName("SectionTitle")
        self.validation_box = QTextEdit()
        self.validation_box.setObjectName("ValidationBox")
        self.validation_box.setReadOnly(True)
        self.validation_box.setAcceptRichText(False)
        self.validation_box.setLineWrapMode(QTextEdit.WidgetWidth)
        self.validation_box.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.validation_box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.validation_box.setPlainText("No validation issues.")

        self.io_box = QTextEdit()
        self.io_box.setObjectName("IOBox")
        self.io_box.setReadOnly(True)
        self.io_box.setAcceptRichText(False)
        self.io_box.setLineWrapMode(QTextEdit.WidgetWidth)
        self.io_box.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.io_box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.io_box.setStyleSheet(_muted_text_style())

        self.helper_title = QLabel("Helper tools")
        self.helper_title.setObjectName("SectionTitle")
        self.helper_container = QWidget()
        self.helper_layout = QVBoxLayout(self.helper_container)
        self.helper_layout.setContentsMargins(0, 0, 0, 0)
        self.helper_layout.setSpacing(8)
        self.helper_layout.addWidget(QLabel("No helper tools for this step."))

        side_layout.addWidget(self.validation_title)
        side_layout.addWidget(self.validation_box)
        side_layout.addWidget(self.io_box)
        side_layout.addWidget(self.helper_title)
        side_layout.addWidget(self.helper_container)
        side_layout.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))

        body.addWidget(self.form_frame)
        body.addWidget(self.side_frame)
        body.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.body_scroll.setWidget(body_host)
        root.addWidget(self.body_scroll, 1)

        self._apply_theme_styles()

    def set_compact_back_enabled(self, enabled: bool) -> None:
        self.btn_back.setVisible(enabled)

    def _apply_theme_styles(self) -> None:
        palette = self.palette()
        self.form_frame.setStyleSheet(_card_frame_style())
        self.side_frame.setStyleSheet(_card_frame_style())
        self.subtitle.setStyleSheet(
            "padding: 8px 10px; border-radius: 10px; background: palette(alternate-base); "
            "border: 1px solid palette(mid); color: palette(text);"
        )
        self.meta_line.setStyleSheet("padding-left: 3px; color: palette(text);")
        self.validation_box.setStyleSheet(_ok_box_style(palette))
        self.io_box.setStyleSheet(_ok_box_style(palette))
        self._resize_info_boxes()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.PaletteChange:
            self._apply_theme_styles()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._resize_info_boxes()
        super().resizeEvent(event)

    def _resize_info_boxes(self) -> None:
        self._autosize_text_box(self.validation_box, min_height=68, max_height=220)
        self._autosize_text_box(self.io_box, min_height=96, max_height=280)

    @staticmethod
    def _autosize_text_box(box: QTextEdit, min_height: int, max_height: int) -> None:
        viewport_width = box.viewport().width()
        if viewport_width <= 0:
            box.setFixedHeight(min_height)
            box.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            return
        doc = box.document()
        margin = float(doc.documentMargin())
        frame = float(box.frameWidth() * 2)
        # Keep a few extra pixels to avoid false-positive vertical scrollbar flicker.
        text_width = max(40.0, float(viewport_width) - (margin * 2.0) - 2.0)
        doc.setTextWidth(text_width)
        target_height = int(doc.size().height() + (margin * 2.0) + frame + 10.0)
        clamped = max(min_height, min(max_height, target_height))
        box.setFixedHeight(clamped)
        if target_height > max_height:
            box.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            box.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def load_process(self, row: int) -> None:
        runtime = self.model.runtime_at(row)
        self._current_row = row
        self._current_step_id = runtime.module.step_id
        self.title.setText(runtime.module.display_name)
        description = runtime.module.description.strip()
        if len(description) > 180:
            description = f"{description[:177]}..."
        self.subtitle.setText(description)
        prereq_count = len(runtime.module.prerequisites)
        prereq_text = f"{prereq_count} prerequisite(s)" if prereq_count else "no prerequisites"
        self.meta_line.setText(f"Step ID: {runtime.module.step_id} | {prereq_text}")

        self._field_specs = runtime.module.parameter_schema()
        self._build_form(self._field_specs, runtime.params)
        self._rebuild_helpers(runtime)
        self._update_io(runtime)
        self._set_inputs_locked(runtime.status in (ProcStatus.DONE, ProcStatus.WARNING))
        self._original_params = self._collect_params()
        self._refresh_validation()
        self._sync_run_action_state(row)

    def _sync_run_action_state(self, row: int) -> None:
        action_text = self.model.action_label_for_row(row)
        self._run_action_text = action_text
        self.btn_run.setText(action_text)
        self.btn_run.setProperty("action_state", action_text.lower().replace(" ", "_"))
        if action_text == "Run Now":
            self.btn_run.setCursor(Qt.PointingHandCursor)
        else:
            self.btn_run.setCursor(Qt.ArrowCursor)
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        self.btn_run.update()

    def _clear_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets.clear()

    def _build_form(self, specs: list[StepParamSpec], values: dict[str, Any]) -> None:
        self._clear_form()
        for spec in specs:
            widget = self._widget_for_spec(spec, values.get(spec.key))
            self._set_param_widget_margin(widget)
            self._widgets[spec.key] = widget
            if spec.param_type == ParamType.BOOLEAN:
                self.form.addRow("", widget)
            else:
                label = QLabel(spec.label)
                label.setMargin(1)
                label.setStyleSheet("padding: 3px;")
                self.form.addRow(label, widget)

    @staticmethod
    def _set_param_widget_margin(widget: QWidget) -> None:
        style = widget.styleSheet().strip()
        margin_rule = "margin: 1px;"
        padding_rule = "padding: 3px;"
        if margin_rule in style and padding_rule in style:
            return
        if style:
            widget.setStyleSheet(f"{style} {margin_rule} {padding_rule}")
        else:
            widget.setStyleSheet(f"{margin_rule} {padding_rule}")

    def _widget_for_spec(self, spec: StepParamSpec, value: Any) -> QWidget:
        widget: QWidget
        if spec.param_type == ParamType.SELECT:
            combo = QComboBox()
            combo.addItems(spec.options)
            if value is not None:
                combo.setCurrentText(str(value))
            combo.currentIndexChanged.connect(self._refresh_validation)
            widget = combo
        elif spec.param_type == ParamType.BOOLEAN:
            checkbox = QCheckBox(spec.label)
            checkbox.setChecked(bool(value))
            checkbox.stateChanged.connect(self._refresh_validation)
            widget = checkbox
        elif spec.param_type == ParamType.INTEGER:
            spin = QSpinBox()
            spin.setRange(int(spec.minimum if spec.minimum is not None else -1_000_000), int(spec.maximum if spec.maximum is not None else 1_000_000))
            if spec.increment is not None:
                spin.setSingleStep(int(spec.increment))
            if spec.unit:
                spin.setSuffix(f" {spec.unit}")
            if value is not None:
                spin.setValue(int(value))
            spin.valueChanged.connect(self._refresh_validation)
            widget = spin
        elif spec.param_type == ParamType.NUMBER:
            dspin = QDoubleSpinBox()
            dspin.setDecimals(3)
            dspin.setRange(
                spec.minimum if spec.minimum is not None else -1_000_000.0,
                spec.maximum if spec.maximum is not None else 1_000_000.0,
            )
            if spec.increment is not None:
                dspin.setSingleStep(float(spec.increment))
            if spec.unit:
                dspin.setSuffix(f" {spec.unit}")
            if value is not None:
                dspin.setValue(float(value))
            dspin.valueChanged.connect(self._refresh_validation)
            widget = dspin
        else:
            line = QLineEdit()
            line.setText("" if value is None else str(value))
            line.textChanged.connect(self._refresh_validation)
            widget = line
        return widget

    def _collect_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for spec in self._field_specs:
            widget = self._widgets[spec.key]
            if spec.param_type == ParamType.SELECT:
                params[spec.key] = str(widget.currentText())  # type: ignore[attr-defined]
            elif spec.param_type == ParamType.BOOLEAN:
                params[spec.key] = bool(widget.isChecked())  # type: ignore[attr-defined]
            elif spec.param_type == ParamType.INTEGER:
                params[spec.key] = int(widget.value())  # type: ignore[attr-defined]
            elif spec.param_type == ParamType.NUMBER:
                params[spec.key] = float(widget.value())  # type: ignore[attr-defined]
            else:
                params[spec.key] = str(widget.text())  # type: ignore[attr-defined]
        return params

    def _set_form_values(self, params: dict[str, Any]) -> None:
        for spec in self._field_specs:
            if spec.key not in self._widgets or spec.key not in params:
                continue
            widget = self._widgets[spec.key]
            value = params[spec.key]
            if spec.param_type == ParamType.SELECT:
                widget.setCurrentText(str(value))  # type: ignore[attr-defined]
            elif spec.param_type == ParamType.BOOLEAN:
                widget.setChecked(bool(value))  # type: ignore[attr-defined]
            elif spec.param_type in (ParamType.INTEGER, ParamType.NUMBER):
                widget.setValue(value)  # type: ignore[attr-defined]
            else:
                widget.setText(str(value))  # type: ignore[attr-defined]

    def _set_inputs_locked(self, locked: bool) -> None:
        self._inputs_locked = locked
        for widget in self._widgets.values():
            widget.setEnabled(not locked)
        self.btn_save.setEnabled(not locked)
        self.btn_revert.setEnabled(not locked)
        for helper_btn in self.helper_container.findChildren(QPushButton):
            helper_btn.setEnabled(not locked)

    def _canonicalize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        canonical: dict[str, Any] = {}
        for spec in self._field_specs:
            if spec.key not in params:
                continue
            value = params[spec.key]
            if spec.param_type == ParamType.SELECT:
                canonical[spec.key] = str(value)
            elif spec.param_type == ParamType.BOOLEAN:
                canonical[spec.key] = bool(value)
            elif spec.param_type == ParamType.INTEGER:
                canonical[spec.key] = int(value)
            elif spec.param_type == ParamType.NUMBER:
                canonical[spec.key] = float(value)
            else:
                canonical[spec.key] = str(value)
        return canonical

    def _saved_params_for_current_step(self) -> dict[str, Any]:
        if self._current_step_id is None:
            return {}
        try:
            runtime = self.engine.step_by_id(self._current_step_id)
        except KeyError:
            return dict(self._original_params)
        return dict(runtime.params)

    def has_unsaved_changes(self) -> bool:
        if self._current_step_id is None:
            return False
        current = self._canonicalize_params(self._collect_params())
        saved = self._canonicalize_params(self._saved_params_for_current_step())
        return current != saved

    def apply_changes(self, notify: bool = False) -> bool:
        if self._current_step_id is None or self._current_row is None:
            return False
        if self._inputs_locked:
            if notify:
                QMessageBox.information(self, "Locked", "Parameters for completed steps are read-only.")
            return False
        params = self._collect_params()
        if not self.has_unsaved_changes():
            if notify:
                QMessageBox.information(self, "Saved", "No parameter changes detected.")
            return True
        self.engine.update_params(self._current_step_id, params)
        self._original_params = self._canonicalize_params(params)
        self.saved.emit(self._current_row)
        if notify:
            QMessageBox.information(self, "Saved", "Parameters saved.")
        return True

    def revert_changes(self, notify: bool = False) -> bool:
        if self._current_step_id is None:
            return False
        if not self.has_unsaved_changes():
            if notify:
                QMessageBox.information(self, "Reverted", "No parameter changes to revert.")
            return True
        saved_params = self._saved_params_for_current_step()
        self._set_form_values(saved_params)
        self._original_params = self._canonicalize_params(saved_params)
        self._refresh_validation()
        if notify:
            QMessageBox.information(self, "Reverted", "Reverted to last saved values.")
        return True

    def _format_issues(self, issues: list[ValidationIssue]) -> str:
        lines: list[str] = []
        for issue in issues:
            prefix = issue.severity.value.upper()
            location = f" [{issue.field}]" if issue.field else ""
            lines.append(f"- {prefix}{location}: {issue.message}")
        return "\n".join(lines)

    def _refresh_validation(self) -> None:
        if self._current_step_id is None:
            return
        params = self._collect_params()
        issues = self.engine.validate_step(self._current_step_id, params_override=params)
        palette = self.palette()
        if not issues:
            self.validation_box.setPlainText("No blocking issues found.")
            self.validation_box.setStyleSheet(_ok_box_style(palette))
            self._resize_info_boxes()
            return
        self.validation_box.setPlainText(self._format_issues(issues))
        self.validation_box.setStyleSheet(_warning_box_style(palette))
        self._resize_info_boxes()

    def _validate_clicked(self) -> None:
        if self._current_step_id is None:
            return
        issues = self.engine.validate_step(self._current_step_id, params_override=self._collect_params())
        if not issues:
            QMessageBox.information(self, "Validation", "No blocking issues found.")
            return
        QMessageBox.warning(self, "Validation", self._format_issues(issues))

    def _save_clicked(self) -> None:
        self.apply_changes(notify=True)

    def _revert_clicked(self) -> None:
        self.revert_changes(notify=True)

    def _run_clicked(self) -> None:
        if self._current_row is None or self._current_step_id is None:
            return
        if self._run_action_text != "Run Now":
            return
        self.run_requested.emit(self._current_row)

    def _update_io(self, runtime: StepRuntime) -> None:
        in_lines = "\n".join(f"- {text}" for text in runtime.module.input_descriptions())
        out_lines = "\n".join(f"- {text}" for text in runtime.module.output_descriptions())
        self.io_box.setPlainText(f"Inputs:\n{in_lines}\n\nOutputs:\n{out_lines}")
        self._resize_info_boxes()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_helpers(self, runtime: StepRuntime) -> None:
        self._clear_layout(self.helper_layout)
        tools = runtime.module.helper_tools()
        if not tools:
            self.helper_layout.addWidget(QLabel("No helper tools for this step."))
            return
        for tool in tools:
            btn = QPushButton(tool.label)
            btn.clicked.connect(lambda _checked=False, tool_id=tool.tool_id: self._apply_helper(tool_id))
            self.helper_layout.addWidget(btn)
            if tool.description:
                desc = QLabel(tool.description)
                desc.setWordWrap(True)
                desc.setStyleSheet(_muted_text_style())
                self.helper_layout.addWidget(desc)

    def _apply_helper(self, tool_id: str) -> None:
        if self._current_step_id is None:
            return
        runtime = self.engine.step_by_id(self._current_step_id)
        updated = runtime.module.apply_helper(tool_id, self._collect_params())
        self._set_form_values(updated)
        self._refresh_validation()


def _quantity_to_um(value: float, unit: str) -> float:
    u = unit.lower().strip()
    if u in ("um", "micrometer", "micrometers"):
        return value
    if u == "nm":
        return value / 1000.0
    if u in ("a", "angstrom", "angstroms"):
        return value / 10000.0
    if u == "mm":
        return value * 1000.0
    return value


def _format_artifact_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return "--:--"


class DraggableProcessList(QListWidget):
    reordered = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._drag_row: int | None = None
        self.setObjectName("ProcessList")
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSpacing(6)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def startDrag(self, supported_actions: Qt.DropActions) -> None:  # type: ignore[override]
        self._drag_row = self.currentRow()
        super().startDrag(supported_actions)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        source_row = self._drag_row
        super().dropEvent(event)
        target_row = self.currentRow()
        self._drag_row = None
        if source_row is None or target_row < 0:
            return
        if source_row != target_row:
            self.reordered.emit(source_row, target_row)


class InsertStepButton(QPushButton):
    hover_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("+", parent)
        self.setObjectName("InsertStepButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._set_hovered(False)

    def _set_hovered(self, hovered: bool) -> None:
        self.setProperty("hovered", hovered)
        if hovered:
            self.setFixedSize(26, 26)
        else:
            self.setFixedSize(18, 18)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._set_hovered(True)
        self.hover_changed.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._set_hovered(False)
        self.hover_changed.emit()
        super().leaveEvent(event)


class ProcessListItemWidget(QFrame):
    clicked = Signal(str)
    run_requested = Signal(int)
    remove_requested = Signal(str)

    def __init__(
        self,
        runtime: StepRuntime,
        row: int,
        action_text: str,
        movable: bool,
        active: bool,
        list_widget: DraggableProcessList,
        edit_enabled: bool,
        can_delete: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row = row
        self._step_id = runtime.module.step_id
        self._list_widget = list_widget
        self._movable = movable
        self._edit_enabled = edit_enabled
        self._can_delete = can_delete
        self._action_text = action_text
        self._drag_start_pos = None
        self._pointer_moved = False
        self.setObjectName("ProcessItem")
        self.setProperty("active", active)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(2, 3, 8, 3)
        row_layout.setSpacing(6)

        self.step_handle = QStackedWidget()
        self.step_handle.setObjectName("StepHandle")
        self.step_handle.setFixedWidth(18)
        self.step_handle.setContentsMargins(0, 0, 0, 0)

        self.step_number = QLabel(str(runtime.order))
        self.step_number.setObjectName("StepNumber")
        self.step_number.setAlignment(Qt.AlignCenter)

        self.grabber = QLabel("::")
        self.grabber.setObjectName("DragGrabber")
        self.grabber.setAlignment(Qt.AlignCenter)

        self.step_handle.addWidget(self.step_number)
        self.step_handle.addWidget(self.grabber)
        self.step_handle.setCurrentWidget(self.step_number)
        self.step_handle.installEventFilter(self)
        self.step_number.installEventFilter(self)
        self.grabber.installEventFilter(self)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.name_label = QLabel(runtime.module.display_name)
        self.name_label.setObjectName("ProcessName")
        self.name_label.setWordWrap(False)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.params_label = QLabel(runtime.key_params)
        self.params_label.setObjectName("ProcessParams")
        self.params_label.setWordWrap(True)
        self.params_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        text_col.addWidget(self.name_label)
        text_col.addWidget(self.params_label)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(6)

        show_delete = self._edit_enabled and self._can_delete
        self.delete_button = QPushButton("Delete", self)
        self.delete_button.setObjectName("DeleteStepButton")
        self.delete_button.setToolTip("Remove step")
        self.delete_button.setMinimumWidth(86)
        self.delete_button.setFixedHeight(26)
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.setVisible(show_delete)
        self.delete_button.clicked.connect(lambda: self.remove_requested.emit(self._step_id))

        show_run_button = (not self._edit_enabled) or action_text == "Done"
        self.run_button = QPushButton(action_text, self)
        self.run_button.setObjectName("RowActionButton")
        action_state = action_text.lower().replace(" ", "_")
        self.run_button.setProperty("action_state", action_state)
        self.run_button.setEnabled(True)
        if action_text == "Run Now":
            self.run_button.setCursor(Qt.PointingHandCursor)
        else:
            self.run_button.setCursor(Qt.ArrowCursor)
        # In edit mode, only keep "Done" visible; hide run/pending/running actions.
        self.run_button.setVisible(show_run_button)
        self.run_button.clicked.connect(self._emit_run)
        self.run_button.setMinimumWidth(86)

        right_col.addStretch(1)
        right_col.addWidget(self.delete_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        right_col.addWidget(self.run_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        right_col.addStretch(1)

        row_layout.addWidget(self.step_handle, 0, Qt.AlignVCenter | Qt.AlignHCenter)
        row_layout.addLayout(text_col, 1)
        row_layout.addLayout(right_col, 0)

    def relayout_for_width(self, item_width: int) -> None:
        row_layout = self.layout()
        if not isinstance(row_layout, QHBoxLayout):
            return
        margins = row_layout.contentsMargins()
        spacing = row_layout.spacing()
        left_block = self.step_handle.sizeHint().width()
        right_block = max(self.run_button.sizeHint().width(), self.delete_button.sizeHint().width())
        text_width = max(
            80,
            item_width - margins.left() - margins.right() - left_block - right_block - (spacing * 2),
        )

        name_metrics = self.name_label.fontMetrics()
        params_metrics = self.params_label.fontMetrics()

        self.name_label.setFixedHeight(name_metrics.lineSpacing())

        single_line = params_metrics.horizontalAdvance(self.params_label.text())
        if single_line <= text_width:
            self.params_label.setWordWrap(False)
            self.params_label.setFixedHeight(params_metrics.lineSpacing())
        else:
            self.params_label.setWordWrap(True)
            wrapped = params_metrics.boundingRect(0, 0, text_width, 2000, Qt.TextWordWrap, self.params_label.text())
            self.params_label.setFixedHeight(max(params_metrics.lineSpacing(), wrapped.height()))

        row_layout.activate()
        self.updateGeometry()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.position()
            self._pointer_moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._drag_start_pos
        if abs(delta.x()) + abs(delta.y()) < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._pointer_moved = True
        if not self._movable:
            return
        visual_row = self._visual_row_for_step()
        if visual_row >= 0:
            self._list_widget.setCurrentRow(visual_row)
            self._list_widget.startDrag(Qt.MoveAction)
        self._drag_start_pos = None

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and not self._pointer_moved:
            self.clicked.emit(self._step_id)
        self._drag_start_pos = None
        self._pointer_moved = False
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.step_handle, self.step_number, self.grabber) and self._movable:
            if event.type() == QEvent.Enter:
                self.step_handle.setCurrentWidget(self.grabber)
            elif event.type() == QEvent.Leave:
                self.step_handle.setCurrentWidget(self.step_number)
        return super().eventFilter(watched, event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.step_handle.setCurrentWidget(self.step_number)
        super().leaveEvent(event)

    def _emit_run(self) -> None:
        if self._action_text != "Run Now":
            return
        self.run_requested.emit(self._row)

    def _visual_row_for_step(self) -> int:
        for vis in range(self._list_widget.count()):
            item = self._list_widget.item(vis)
            if str(item.data(Qt.UserRole)) == self._step_id:
                return vis
        return -1


class ProcessListColumn(QFrame):
    step_selected = Signal(int)
    run_requested = Signal(int)
    reorder_requested = Signal(str, int)
    add_requested = Signal(int)
    remove_requested = Signal(str)
    restart_requested = Signal()
    edit_mode_changed = Signal(bool)

    def __init__(self, model: ProcessTableModel) -> None:
        super().__init__()
        self.model = model
        self._selected_step_id: str | None = None
        self._filtered_rows: list[int] = []
        self._drag_enabled = True
        self._updating_selection = False
        self._edit_enabled = False
        self._insert_buttons: list[tuple[InsertStepButton, int]] = []

        self.setObjectName("Card")
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 10, 10)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("Process Chain")
        title.setObjectName("ColumnTitle")
        self.btn_restart = QPushButton("Restart Chain")
        self.btn_restart.setObjectName("SecondaryActionButton")
        self.btn_restart.clicked.connect(self.restart_requested.emit)
        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setObjectName("TopButton")
        self.btn_edit.setCheckable(True)
        self.btn_edit.toggled.connect(self._on_edit_toggled)
        title_row.addWidget(title)
        title_row.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))
        title_row.addWidget(self.btn_restart)
        title_row.addWidget(self.btn_edit)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("Search process...")
        self.search.textChanged.connect(self._refresh_filtered_view)

        self.status = QComboBox()
        self.status.setObjectName("StatusFilter")
        self.status.addItems(["All"] + [s.value for s in ProcStatus])
        self.status.currentTextChanged.connect(self._refresh_filtered_view)

        filters.addWidget(self.search, 3)
        filters.addWidget(self.status, 2)

        self.reorder_hint = QLabel("Enable Edit to reorder unfinished steps. Clear filters to reorder.")
        self.reorder_hint.setObjectName("MutedText")
        self.reorder_hint.setWordWrap(True)

        self.list = DraggableProcessList()
        self.list.setViewportMargins(0, 0, 2, 0)
        self.list.reordered.connect(self._on_reordered)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.verticalScrollBar().valueChanged.connect(self._position_insert_buttons)

        root.addLayout(title_row)
        root.addLayout(filters)
        root.addWidget(self.reorder_hint)
        root.addWidget(self.list, 1)

    def selected_step_id(self) -> str | None:
        return self._selected_step_id

    def set_edit_enabled(self, enabled: bool) -> None:
        if self.btn_edit.isChecked() != enabled:
            self.btn_edit.setChecked(enabled)
        self._edit_enabled = enabled
        self._refresh_filtered_view()

    def _on_edit_toggled(self, checked: bool) -> None:
        self._edit_enabled = checked
        self.edit_mode_changed.emit(checked)
        self._refresh_filtered_view()

    def set_selected_step_id(self, step_id: str | None) -> None:
        self._selected_step_id = step_id
        self._restore_selection()
        self._apply_active_markers()

    def refresh(self, selected_step_id: str | None = None) -> None:
        if selected_step_id is not None:
            self._selected_step_id = selected_step_id
        self._refresh_filtered_view()

    def _refresh_filtered_view(self) -> None:
        search = self.search.text().strip().lower()
        status_value = self.status.currentText()
        self._drag_enabled = self._edit_enabled and search == "" and status_value == "All"
        self.reorder_hint.setVisible(True)
        scroll = self.list.verticalScrollBar().value()

        self.setUpdatesEnabled(False)
        self.list.setUpdatesEnabled(False)
        self.list.blockSignals(True)
        self._updating_selection = True
        self.list.clear()
        self._filtered_rows.clear()
        self._clear_insert_buttons()

        if self._drag_enabled:
            self.list.setDragDropMode(QAbstractItemView.InternalMove)
            self.list.setDragEnabled(True)
        else:
            self.list.setDragDropMode(QAbstractItemView.NoDragDrop)
            self.list.setDragEnabled(False)

        for row in range(self.model.rowCount()):
            runtime = self.model.runtime_at(row)
            haystack = f"{runtime.module.display_name} {runtime.module.description} {runtime.key_params}".lower()
            if search and search not in haystack:
                continue
            if status_value != "All" and runtime.status.value != status_value:
                continue

            action = self.model.action_label_for_row(row)
            movable = self._drag_enabled and self.model.is_row_movable(row)
            can_delete = self._edit_enabled and self.model.is_row_movable(row)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, runtime.module.step_id)
            item.setData(Qt.UserRole + 1, row)
            item_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if movable:
                item_flags |= Qt.ItemIsDragEnabled
            item.setFlags(item_flags)
            row_widget = ProcessListItemWidget(
                runtime=runtime,
                row=row,
                action_text=action,
                movable=movable,
                active=(runtime.module.step_id == self._selected_step_id),
                list_widget=self.list,
                edit_enabled=self._edit_enabled,
                can_delete=can_delete,
                parent=self.list.viewport(),
            )
            row_widget.clicked.connect(self._emit_step_selected)
            row_widget.run_requested.connect(self.run_requested.emit)
            row_widget.remove_requested.connect(self.remove_requested.emit)

            item.setSizeHint(row_widget.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row_widget)
            self._filtered_rows.append(row)

        self._relayout_list_rows()
        self._restore_selection()
        self._apply_active_markers()
        self.list.verticalScrollBar().setValue(scroll)
        self._update_minimum_width()
        self._rebuild_insert_buttons()
        self._position_insert_buttons()
        self._updating_selection = False
        self.list.blockSignals(False)
        self.list.setUpdatesEnabled(True)
        self.setUpdatesEnabled(True)

    def _restore_selection(self) -> None:
        if self.list.count() <= 0:
            return

        selected_vis = -1
        if self._selected_step_id:
            for vis in range(self.list.count()):
                step_id = str(self.list.item(vis).data(Qt.UserRole))
                if step_id == self._selected_step_id:
                    selected_vis = vis
                    break
        if selected_vis < 0:
            selected_vis = 0
            self._selected_step_id = str(self.list.item(0).data(Qt.UserRole))
        if self.list.currentRow() != selected_vis:
            self.list.setCurrentRow(selected_vis)

    def _apply_active_markers(self) -> None:
        for vis in range(self.list.count()):
            item = self.list.item(vis)
            row_widget = self.list.itemWidget(item)
            if not isinstance(row_widget, ProcessListItemWidget):
                continue
            step_id = str(item.data(Qt.UserRole))
            is_active = step_id == self._selected_step_id
            row_widget.setProperty("active", is_active)
            row_widget.style().unpolish(row_widget)
            row_widget.style().polish(row_widget)
            row_widget.update()

    def _emit_step_selected(self, step_id: str) -> None:
        source_row = self.model.row_for_step(step_id)
        if source_row is None:
            return
        self._selected_step_id = step_id
        self._restore_selection()
        self._apply_active_markers()
        self.step_selected.emit(source_row)

    def _on_selection_changed(self) -> None:
        if self._updating_selection:
            return
        current = self.list.currentItem()
        if current is None:
            return
        step_id = str(current.data(Qt.UserRole))
        source_row = self.model.row_for_step(step_id)
        if source_row is None:
            return
        self._selected_step_id = step_id
        self._apply_active_markers()
        self.step_selected.emit(source_row)

    def _on_reordered(self, source_vis: int, target_vis: int) -> None:
        if not self._drag_enabled:
            self._refresh_filtered_view()
            return
        if source_vis < 0 or target_vis < 0:
            self._refresh_filtered_view()
            return
        if target_vis >= self.list.count():
            target_vis = self.list.count() - 1
        moved_item = self.list.item(target_vis)
        if moved_item is None:
            self._refresh_filtered_view()
            return
        step_id = str(moved_item.data(Qt.UserRole))
        self._selected_step_id = step_id
        self.reorder_requested.emit(step_id, target_vis)

    def _clear_insert_buttons(self) -> None:
        for button, _index in self._insert_buttons:
            button.hide()
            button.deleteLater()
        self._insert_buttons.clear()

    def _rebuild_insert_buttons(self) -> None:
        self._clear_insert_buttons()
        if not self._drag_enabled:
            return
        row_count = self.model.rowCount()
        if row_count < 0:
            return
        first_unfinished = self.model.first_unfinished_row()
        indices: list[int] = []
        if first_unfinished is not None:
            for row in range(first_unfinished, row_count):
                indices.append(row)
        indices.append(row_count)

        for target_index in indices:
            btn = InsertStepButton(self.list.viewport())
            btn.setToolTip("Add step here")
            btn.clicked.connect(lambda _checked=False, idx=target_index: self.add_requested.emit(idx))
            btn.hover_changed.connect(self._position_insert_buttons)
            btn.setVisible(False)
            self._insert_buttons.append((btn, target_index))

    def _relayout_list_rows(self) -> None:
        if self.list.count() <= 0:
            return
        viewport_width = max(220, self.list.viewport().width() - 4)
        for vis in range(self.list.count()):
            item = self.list.item(vis)
            row_widget = self.list.itemWidget(item)
            if not isinstance(row_widget, ProcessListItemWidget):
                continue
            row_widget.relayout_for_width(viewport_width)
            item.setSizeHint(row_widget.sizeHint())

    def _visual_index_for_source_row(self, source_row: int) -> int:
        for vis in range(self.list.count()):
            item = self.list.item(vis)
            src = int(item.data(Qt.UserRole + 1))
            if src == source_row:
                return vis
        return -1

    def _position_insert_buttons(self) -> None:
        if not self._insert_buttons:
            return
        viewport = self.list.viewport()
        vpw = viewport.width()
        row_count = self.model.rowCount()
        spacing_offset = max(1, self.list.spacing())
        for btn, target_index in self._insert_buttons:
            x = (vpw - btn.width()) // 2
            y = 4
            if target_index < row_count:
                vis = self._visual_index_for_source_row(target_index)
                if vis < 0:
                    btn.hide()
                    continue
                rect = self.list.visualItemRect(self.list.item(vis))
                y = rect.top() - (btn.height() // 2) - spacing_offset
            else:
                if self.list.count() > 0:
                    last_rect = self.list.visualItemRect(self.list.item(self.list.count() - 1))
                    y = last_rect.bottom() + (self.list.spacing() // 2) - (btn.height() // 2) + spacing_offset
            btn.move(max(0, x), max(0, y))
            btn.show()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout_list_rows()
        self._position_insert_buttons()

    def _update_minimum_width(self) -> None:
        metrics = QFontMetrics(self.font())
        max_title = 0
        for row in range(self.model.rowCount()):
            runtime = self.model.runtime_at(row)
            max_title = max(max_title, metrics.horizontalAdvance(runtime.module.display_name))
        button_width = max(
            metrics.horizontalAdvance("Run Now"),
            metrics.horizontalAdvance("Pending"),
            metrics.horizontalAdvance("Running"),
        ) + 28
        left_block = 24
        min_width = left_block + max_title + button_width + 116
        self.setMinimumWidth(max(320, min_width))


class CrossSectionCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._state: SampleState | None = None
        self.setMinimumHeight(210)
        self.setObjectName("CrossSectionCanvas")

    def set_state(self, state: SampleState) -> None:
        self._state = state
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = self.palette()
        base = palette.color(QPalette.Base)
        alt = palette.color(QPalette.AlternateBase)
        border = palette.color(QPalette.Mid)
        text = palette.color(QPalette.Text)
        highlight = palette.color(QPalette.Highlight)

        area = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(area, base)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(area, 8, 8)

        if self._state is None or self._state.substrate is None:
            painter.setPen(text)
            painter.drawText(area, Qt.AlignCenter, "No substrate loaded")
            painter.end()
            return

        substrate = self._state.substrate
        left = area.left() + 1
        top = area.top() + 1
        width = max(1, area.width() - 2)
        height = max(1, area.height() - 2)
        substrate_h = max(26, int(height * 0.16))
        layer_top = top + height - substrate_h

        substrate_rect = area.adjusted(1, height - substrate_h, -1, -1)
        painter.fillRect(substrate_rect, alt)

        segment_count = self._segment_count(self._state)
        segment_count = max(1, min(segment_count, 64))
        col_w = float(width) / float(segment_count)
        surface = [float(layer_top) for _ in range(segment_count)]

        for layer in self._state.layers:
            if layer.status != "present":
                continue
            thick_um = _quantity_to_um(float(layer.thickness.value), str(layer.thickness.unit))
            layer_h = self._visual_layer_height(thick_um)
            segments = layer.facets.get("geometry.segments", [])

            if isinstance(segments, list) and segments:
                columns = self._segment_column_spans(segments, segment_count)
                for start, end, segment in columns:
                    seg_state = str(segment.get("state", "material")).lower()
                    if seg_state == "void":
                        continue
                    color = self._segment_color(layer.role, layer.material, seg_state, highlight, border, alt)
                    for idx in range(start, end):
                        x = int(left + idx * col_w)
                        w = int(max(1, col_w + 1))
                        y = int(surface[idx] - layer_h)
                        painter.fillRect(x, y, w, int(layer_h), color)
                        surface[idx] = float(y)
            else:
                color = self._segment_color(layer.role, layer.material, "material", highlight, border, alt)
                for idx in range(segment_count):
                    x = int(left + idx * col_w)
                    w = int(max(1, col_w + 1))
                    y = int(surface[idx] - layer_h)
                    painter.fillRect(x, y, w, int(layer_h), color)
                    surface[idx] = float(y)

        painter.setPen(text)
        painter.drawText(
            area.adjusted(8, 4, -8, -6),
            Qt.AlignLeft | Qt.AlignBottom,
            f"Substrate: {substrate.material}  |  Resolution: {segment_count} cols",
        )
        painter.end()

    @staticmethod
    def _visual_layer_height(thickness_um: float) -> int:
        if thickness_um < 0.05:
            return 4
        if thickness_um < 0.3:
            return 8
        if thickness_um < 2.0:
            return 13
        if thickness_um < 10.0:
            return 18
        return 24

    @staticmethod
    def _segment_count(state: SampleState) -> int:
        count = 1
        for layer in state.layers:
            segments = layer.facets.get("geometry.segments", [])
            if isinstance(segments, list):
                count = max(count, len(segments))
        return count

    @staticmethod
    def _segment_column_spans(segments: list[dict[str, Any]], count: int) -> list[tuple[int, int, dict[str, Any]]]:
        safe: list[tuple[int, int, dict[str, Any]]] = []
        cursor = 0
        for idx, segment in enumerate(segments):
            fraction = float(segment.get("fraction", 1.0 / max(1, len(segments))))
            width = int(round(fraction * count))
            if idx == len(segments) - 1:
                end = count
            else:
                end = min(count, max(cursor + 1, cursor + width))
            if end > cursor:
                safe.append((cursor, end, segment))
            cursor = end
        if not safe:
            safe.append((0, count, {"state": "material"}))
        return safe

    @staticmethod
    def _segment_color(
        role: str,
        material: str,
        seg_state: str,
        highlight: QColor,
        border: QColor,
        alt: QColor,
    ) -> QColor:
        base = CrossSectionCanvas._material_color(material, role, highlight, border, alt)
        if seg_state == "exposed":
            return base.darker(130)
        if seg_state == "developed":
            return base.lighter(115)
        return base

    @staticmethod
    def _material_color(material: str, role: str, highlight: QColor, border: QColor, alt: QColor) -> QColor:
        token = material.strip().lower()
        palette_map = {
            "cr": QColor("#8b949e"),
            "chromium": QColor("#8b949e"),
            "au": QColor("#d4af37"),
            "gold": QColor("#d4af37"),
            "al": QColor("#c0c5ce"),
            "aluminum": QColor("#c0c5ce"),
            "aluminium": QColor("#c0c5ce"),
            "ti": QColor("#6b7280"),
            "titanium": QColor("#6b7280"),
            "cu": QColor("#b87333"),
            "copper": QColor("#b87333"),
            "ni": QColor("#9aa0a6"),
            "nickel": QColor("#9aa0a6"),
            "az10xt": QColor("#ef4444"),
            "s1813": QColor("#f97316"),
            "su-8": QColor("#c2410c"),
            "pmma": QColor("#f59e0b"),
        }
        if token in palette_map:
            return palette_map[token]
        if role == "resist":
            return highlight.lighter(110)
        if role == "metal":
            return border
        return alt.darker(110)


class CrossSectionCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("Cross Section")
        self.title.setObjectName("ColumnTitle")
        self.subtitle = QLabel("No sample")
        self.subtitle.setObjectName("MutedText")
        self.subtitle.setWordWrap(True)
        header.addWidget(self.title)
        header.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))
        root.addLayout(header)
        root.addWidget(self.subtitle)

        self.canvas = CrossSectionCanvas()
        root.addWidget(self.canvas, 1)

        stats = QHBoxLayout()
        self.total = QLabel("Total thickness: --")
        self.total.setObjectName("MutedText")
        self.count = QLabel("Layers: 0")
        self.count.setObjectName("MutedText")
        stats.addWidget(self.total)
        stats.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))
        stats.addWidget(self.count)
        root.addLayout(stats)

    def set_state(self, state: SampleState) -> None:
        self.canvas.set_state(state)
        if state.substrate is None:
            self.subtitle.setText("No substrate")
            self.total.setText("Total thickness: --")
            self.count.setText("Layers: 0")
            return

        desc = state.substrate.surface_finish or "unknown"
        self.subtitle.setText(f"{state.substrate.material} [{desc}]")
        total_um = 0.0
        if state.substrate.geometry:
            total_um = float(state.substrate.geometry.get("thickness_um", 0.0))
        for layer in state.layers:
            if layer.status != "present":
                continue
            total_um += _quantity_to_um(float(layer.thickness.value), str(layer.thickness.unit))
        self.total.setText(f"Total thickness: {total_um:.3f} um")
        self.count.setText(f"Layers: {len(state.layers)}")


class ArtifactsCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("Artifacts")
        title.setObjectName("ColumnTitle")
        root.addWidget(title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("ArtifactScroll")

        self.content = QWidget()
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.scroll.setWidget(self.content)

        root.addWidget(self.scroll, 1)

    def set_artifacts(self, artifacts: list[ArtifactRef]) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not artifacts:
            empty = QLabel("No artifacts generated yet.")
            empty.setObjectName("MutedText")
            self.list_layout.insertWidget(0, empty)
            return

        for artifact in reversed(artifacts[-12:]):
            card = QFrame()
            card.setObjectName("ArtifactItem")
            row = QVBoxLayout(card)
            row.setContentsMargins(8, 8, 8, 8)
            row.setSpacing(2)
            summary = QLabel(artifact.summary or artifact.uri)
            summary.setObjectName("ArtifactSummary")
            summary.setWordWrap(True)
            meta = QLabel(f"{artifact.kind} | {_format_artifact_time(artifact.created_at)} | {artifact.uri}")
            meta.setObjectName("MutedText")
            meta.setWordWrap(True)
            row.addWidget(summary)
            row.addWidget(meta)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)


class TopBar(QFrame):
    cross_section_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TopBar")

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(10)

        logo = QLabel("N")
        logo.setObjectName("LogoBadge")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(28, 28)

        brand = QLabel("NanoFab <span style='font-weight:300;'>Manager</span>")
        brand.setObjectName("BrandText")
        brand.setTextFormat(Qt.RichText)

        self.cross_btn = QPushButton("Cross Section")
        self.cross_btn.setObjectName("TopButton")
        self.cross_btn.clicked.connect(self.cross_section_requested.emit)

        self.system_dot = QLabel("")
        self.system_dot.setObjectName("SystemDot")
        self.system_dot.setFixedSize(10, 10)

        self.system_label = QLabel("System Online")
        self.system_label.setObjectName("MutedText")

        self.id_label = QLabel("ID: --")
        self.id_label.setObjectName("TopId")

        root.addWidget(logo)
        root.addWidget(brand)
        root.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))
        root.addWidget(self.cross_btn)
        root.addWidget(self.system_dot)
        root.addWidget(self.system_label)
        root.addWidget(self.id_label)

    def set_id_text(self, text: str) -> None:
        self.id_label.setText(text)

    def set_cross_active(self, active: bool) -> None:
        self.cross_btn.setProperty("active", active)
        self.cross_btn.style().unpolish(self.cross_btn)
        self.cross_btn.style().polish(self.cross_btn)
        self.cross_btn.update()


class VizOverlayDialog(QDialog):
    visibility_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cross Section and Artifacts")
        self.resize(900, 680)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Cross Section and Artifacts")
        title.setObjectName("ColumnTitle")
        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryActionButton")
        close_btn.clicked.connect(self.hide)
        top.addWidget(title)
        top.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))
        top.addWidget(close_btn)

        self.cross = CrossSectionCard()
        self.artifacts = ArtifactsCard()
        body = QSplitter(Qt.Vertical)
        body.setChildrenCollapsible(False)
        body.addWidget(self.cross)
        body.addWidget(self.artifacts)
        body.setStretchFactor(0, 2)
        body.setStretchFactor(1, 1)

        root.addLayout(top)
        root.addWidget(body, 1)

    def set_state(self, state: SampleState) -> None:
        self.cross.set_state(state)
        self.artifacts.set_artifacts(state.artifacts)

    def showEvent(self, event) -> None:  # type: ignore[override]
        self.visibility_changed.emit(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self.visibility_changed.emit(False)
        super().hideEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(820, 560)
        self.setWindowIcon(_icon_from_theme_or_fallback("applications-science", QColor("#2b579a")))
        self.resize(1260, 760)

        self._module_catalog = self._build_module_catalog()
        self.engine = ProcessEngine(build_default_modules())
        self.model = ProcessTableModel(self.engine)
        self._selected_step_id: str | None = None
        self._layout_mode: str = "wide"
        self._last_layout_mode: str = ""
        self._compact_view: str = "list"
        self._right_column_enabled: bool = True
        self._edit_mode_enabled: bool = False
        self._palette_refresh_guard: bool = False
        self._palette_refresh_scheduled: bool = False

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        self.top_bar = TopBar()
        self.top_bar.cross_section_requested.connect(self._handle_cross_section_request)
        root_layout.addWidget(self.top_bar)

        self.body_splitter = QSplitter(Qt.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.setHandleWidth(5)

        self.left_col = ProcessListColumn(self.model)
        self.center_col = RecipeCardView(self.engine, self.model)
        self.center_col.set_compact_back_enabled(False)

        self.right_col = QWidget()
        right_layout = QVBoxLayout(self.right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        self.cross_card = CrossSectionCard()
        self.artifacts_card = ArtifactsCard()
        right_layout.addWidget(self.cross_card, 3)
        right_layout.addWidget(self.artifacts_card, 2)

        self.body_splitter.addWidget(self.left_col)
        self.body_splitter.addWidget(self.center_col)
        self.body_splitter.addWidget(self.right_col)
        self.body_splitter.setStretchFactor(0, 4)
        self.body_splitter.setStretchFactor(1, 5)
        self.body_splitter.setStretchFactor(2, 3)
        self.body_splitter.setSizes([430, 520, 320])

        root_layout.addWidget(self.body_splitter, 1)
        self.setCentralWidget(root)

        self._build_shortcuts()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready. Select a process step.")

        self.left_col.step_selected.connect(self._on_step_selected)
        self.left_col.run_requested.connect(self._run_row_from_list)
        self.left_col.reorder_requested.connect(self._on_reorder_requested)
        self.left_col.add_requested.connect(self._add_step_at)
        self.left_col.remove_requested.connect(self._remove_step_by_id)
        self.left_col.restart_requested.connect(self._restart_chain)
        self.left_col.edit_mode_changed.connect(self._on_edit_mode_changed)
        self.center_col.saved.connect(self._on_saved)
        self.center_col.run_requested.connect(self._run_row_from_setup)
        self.center_col.back_requested.connect(self._back_to_list_compact)

        self.viz_overlay = VizOverlayDialog(self)
        self.viz_overlay.visibility_changed.connect(self.top_bar.set_cross_active)
        self._apply_style_sheet()

        if self.model.rowCount() > 0:
            self._selected_step_id = self.model.step_id_at(0)
            self._select_step_id(self._selected_step_id, open_center=False)
        self._refresh_right_column()
        self.left_col.refresh(self._selected_step_id)
        self._apply_responsive_layout()

    def _build_shortcuts(self) -> None:
        icon_run = _icon_from_theme_or_fallback("media-playback-start", QColor("#2e7d32"))
        icon_step = _icon_from_theme_or_fallback("go-next", QColor("#1565c0"))
        icon_back = _icon_from_theme_or_fallback("go-previous", QColor("#444444"))

        self.act_back = QAction(icon_back, "Back to List", self)
        self.act_run_next = QAction(icon_step, "Run Next Ready", self)
        self.act_run_all = QAction(icon_run, "Run All Ready", self)
        self.act_open_viz = QAction("Cross Section", self)

        self.act_back.setShortcut(QKeySequence.Back)
        self.act_run_next.setShortcut(QKeySequence("Ctrl+N"))
        self.act_run_all.setShortcut(QKeySequence("Ctrl+R"))
        self.act_open_viz.setShortcut(QKeySequence("Ctrl+I"))

        self.act_back.triggered.connect(self._back_to_list_compact)
        self.act_run_next.triggered.connect(self._run_next_ready)
        self.act_run_all.triggered.connect(self._run_all_ready)
        self.act_open_viz.triggered.connect(self._handle_cross_section_request)

        self.addAction(self.act_back)
        self.addAction(self.act_run_next)
        self.addAction(self.act_run_all)
        self.addAction(self.act_open_viz)

    def _build_module_catalog(self) -> list[tuple[type[ProcessStepModule], str, str]]:
        seen: set[type[ProcessStepModule]] = set()
        catalog: list[tuple[type[ProcessStepModule], str, str]] = []
        for module in build_default_modules():
            module_cls = module.__class__
            if module_cls in seen:
                continue
            seen.add(module_cls)
            sample = module_cls()
            catalog.append((module_cls, sample.display_name, sample.description))
        return catalog

    def _select_step_id(self, step_id: str, open_center: bool = True) -> None:
        row = self.model.row_for_step(step_id)
        if row is None:
            return
        self._selected_step_id = step_id
        self.center_col.load_process(row)
        if open_center:
            self._compact_view = "detail"
        self.left_col.set_selected_step_id(self._selected_step_id)
        self._apply_responsive_layout()

    def _confirm_pending_setup_changes(
        self,
        restore_left_selection: bool = False,
        run_context: bool = False,
        run_target_step_id: str | None = None,
    ) -> bool:
        if not self.center_col.has_unsaved_changes():
            return True
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Question)
        dialog.setWindowTitle("Unsaved Changes")
        if run_context:
            if run_target_step_id is not None and run_target_step_id != self._selected_step_id:
                dialog.setText("The selected setup has unsaved parameter changes.")
                dialog.setInformativeText(
                    "Apply to keep those changes before running the other step, Revert to discard, or Cancel."
                )
            else:
                dialog.setText("This ready step has unsaved parameter changes.")
                dialog.setInformativeText("Apply to run with updated values, Revert to run with saved values, or Cancel.")
        else:
            dialog.setText("The current setup has unsaved parameter changes.")
            dialog.setInformativeText("Choose Apply to keep changes, Revert to discard, or Cancel to stay on this step.")
        apply_btn = dialog.addButton("Apply", QMessageBox.AcceptRole)
        revert_btn = dialog.addButton("Revert", QMessageBox.DestructiveRole)
        cancel_btn = dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.setDefaultButton(apply_btn)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked is apply_btn:
            self.center_col.apply_changes(notify=False)
            return True
        if clicked is revert_btn:
            self.center_col.revert_changes(notify=False)
            return True

        if restore_left_selection:
            self.left_col.set_selected_step_id(self._selected_step_id)
        if clicked is cancel_btn:
            return False
        return False

    def _on_step_selected(self, source_row: int) -> None:
        try:
            step_id = self.model.step_id_at(source_row)
        except IndexError:
            return
        if step_id == self._selected_step_id:
            return
        if not self._confirm_pending_setup_changes(restore_left_selection=True):
            return
        self._select_step_id(step_id, open_center=True)
        runtime = self.model.runtime_at(source_row)
        self.statusBar().showMessage(f"Selected step {runtime.order}: {runtime.module.display_name}")

    def _back_to_list_compact(self) -> None:
        if self._layout_mode != "compact":
            return
        if not self._confirm_pending_setup_changes():
            return
        self._compact_view = "list"
        self._apply_responsive_layout()

    def _on_saved(self, row: int) -> None:
        try:
            runtime = self.model.runtime_at(row)
        except IndexError:
            self._refresh_views()
            return
        self._selected_step_id = runtime.module.step_id
        self._refresh_views()
        self.statusBar().showMessage(f"Saved parameters for step {runtime.order}: {runtime.module.display_name}")

    def _run_row(self, row: int) -> None:
        try:
            runtime = self.model.runtime_at(row)
        except IndexError:
            self._refresh_views()
            return
        if self.model.action_label_for_row(row) != "Run Now":
            self.statusBar().showMessage("Only the next ready step can be run.", 3500)
            return
        try:
            result = self.engine.run_step(runtime.module.step_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot run step", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Step failed", str(exc))
            return

        self._selected_step_id = runtime.module.step_id
        self._refresh_views()

        message = f"Completed step {runtime.order}: {runtime.module.display_name}"
        if result.warning:
            message += " (with warning)"
            QMessageBox.warning(self, "Step completed with warning", result.warning)
        self.statusBar().showMessage(message)

    def _run_row_from_list(self, row: int) -> None:
        try:
            step_id = self.model.step_id_at(row)
        except IndexError:
            self._refresh_views()
            return
        if not self._confirm_pending_setup_changes(run_context=True, run_target_step_id=step_id):
            return
        refreshed_row = self.model.row_for_step(step_id)
        if refreshed_row is None:
            self._refresh_views()
            return
        self._run_row(refreshed_row)

    def _run_row_from_setup(self, row: int) -> None:
        try:
            runtime = self.model.runtime_at(row)
        except IndexError:
            self._refresh_views()
            return
        if self.model.action_label_for_row(row) != "Run Now":
            self.statusBar().showMessage("Only the next ready step can be run from setup.", 3500)
            return
        if not self._confirm_pending_setup_changes(run_context=True, run_target_step_id=runtime.module.step_id):
            return
        refreshed_row = self.model.row_for_step(runtime.module.step_id)
        if refreshed_row is None:
            self._refresh_views()
            return
        self._run_row(refreshed_row)

    def _run_next_ready(self) -> None:
        next_ready = self.engine.run_next_ready()
        if next_ready is None:
            QMessageBox.information(self, "Run Next Ready", "No ready steps available.")
            return
        step_id, result = next_ready
        runtime = self.engine.step_by_id(step_id)
        self._selected_step_id = step_id
        self._refresh_views()
        message = f"Ran next ready step {runtime.order}: {runtime.module.display_name}"
        if result.warning:
            message += " (with warning)"
        self.statusBar().showMessage(message)

    def _run_all_ready(self) -> None:
        completed = 0
        for _ in range(len(self.engine.steps_in_order())):
            ready = self.engine.ready_steps()
            if not ready:
                break
            runtime = ready[0]
            try:
                self.engine.run_step(runtime.module.step_id)
            except Exception as exc:
                QMessageBox.warning(self, "Run All Ready", f"Stopped on {runtime.module.display_name}: {exc}")
                break
            completed += 1

        self._refresh_views()
        self.statusBar().showMessage(f"Run-all completed {completed} step(s).")

    def _on_reorder_requested(self, step_id: str, target_index: int) -> None:
        if not self._edit_mode_enabled:
            self.left_col.refresh(self._selected_step_id)
            return
        moved = self.model.move_step_id(step_id, target_index)
        if not moved:
            self.statusBar().showMessage("Reorder ignored. Done/running steps are fixed.", 4000)
            self.left_col.refresh(self._selected_step_id)
            return
        self._selected_step_id = step_id
        self._refresh_views()
        runtime = self.engine.step_by_id(step_id)
        self.statusBar().showMessage(f"Moved step {runtime.order}: {runtime.module.display_name}")

    def _on_edit_mode_changed(self, enabled: bool) -> None:
        self._edit_mode_enabled = enabled
        if enabled:
            self.statusBar().showMessage("Edit mode enabled: reorder, add, and delete unlocked for unfinished steps.")
        else:
            self.statusBar().showMessage("Edit mode disabled.")

    def _add_step_at(self, target_index: int) -> None:
        if not self._edit_mode_enabled:
            return
        first_unfinished = self.model.first_unfinished_row()
        if first_unfinished is not None and target_index < first_unfinished:
            self.statusBar().showMessage("Cannot insert before done steps.", 4000)
            return
        labels = [f"{name} - {desc}" for _, name, desc in self._module_catalog]
        choice, ok = QInputDialog.getItem(
            self,
            "Add Process Step",
            "Select process to insert:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        selected_idx = labels.index(choice)
        module_cls = self._module_catalog[selected_idx][0]
        module = module_cls()
        try:
            new_step_id = self.engine.insert_step(module, target_index)
        except ValueError as exc:
            QMessageBox.warning(self, "Add Step", str(exc))
            return
        self._selected_step_id = new_step_id
        self._refresh_views()
        runtime = self.engine.step_by_id(new_step_id)
        self.statusBar().showMessage(f"Added step {runtime.order}: {runtime.module.display_name}")

    def _remove_step_by_id(self, step_id: str) -> None:
        if not self._edit_mode_enabled:
            return
        row_before = self.model.row_for_step(step_id)
        removed = self.engine.remove_step(step_id)
        if not removed:
            self.statusBar().showMessage("Cannot remove done/running steps.", 4000)
            return
        if self._selected_step_id == step_id:
            if self.model.rowCount() > 0:
                fallback_row = max(0, min((row_before or 0), self.model.rowCount() - 1))
                self._selected_step_id = self.model.step_id_at(fallback_row)
            else:
                self._selected_step_id = None
        self._refresh_views()
        self.statusBar().showMessage("Step removed.")

    def _restart_chain(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Restart Chain",
            "Reset runtime state and step statuses for the current chain?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.engine.restart_chain()
        if self.model.rowCount() > 0:
            first = self.model.runtime_at(0).module.step_id
            self._selected_step_id = first
        self._refresh_views()
        self.statusBar().showMessage("Chain restarted.")

    def _refresh_right_column(self) -> None:
        self.cross_card.set_state(self.engine.current_state)
        self.artifacts_card.set_artifacts(self.engine.current_state.artifacts)
        self.viz_overlay.set_state(self.engine.current_state)
        substrate_id = "--"
        substrate = self.engine.current_state.substrate
        if substrate is not None:
            substrate_id = substrate.lot_id or f"rev-{self.engine.current_state.revision}"
        self.top_bar.set_id_text(f"ID: {substrate_id}")

    def _refresh_views(self) -> None:
        self.model.refresh()
        if self._selected_step_id is None and self.model.rowCount() > 0:
            self._selected_step_id = self.model.step_id_at(0)
        if self._selected_step_id is not None:
            row = self.model.row_for_step(self._selected_step_id)
            if row is not None:
                self.center_col.load_process(row)
        self.left_col.refresh(self._selected_step_id)
        self._refresh_right_column()
        self._apply_responsive_layout()

    def _layout_mode_for_width(self) -> str:
        width = self.width()
        if width >= 1200:
            return "wide"
        if width >= 960:
            return "medium"
        return "compact"

    def _apply_responsive_layout(self) -> None:
        new_mode = self._layout_mode_for_width()
        mode_changed = new_mode != self._last_layout_mode
        self._layout_mode = new_mode
        self._last_layout_mode = new_mode
        has_selection = self._selected_step_id is not None
        prev_right_visible = self.right_col.isVisible()

        self.left_col._update_minimum_width()

        if self._layout_mode == "wide":
            self.left_col.setVisible(True)
            self.center_col.setVisible(True)
            show_right = self._right_column_enabled
            self.right_col.setVisible(show_right)
            self.center_col.set_compact_back_enabled(False)
            self.act_back.setEnabled(False)
            right_visibility_changed = prev_right_visible != show_right
            if mode_changed or right_visibility_changed:
                min_left = max(self.left_col.minimumWidth(), int(self.width() * 0.34))
                if show_right:
                    self.body_splitter.setSizes([min_left, int(self.width() * 0.42), int(self.width() * 0.24)])
                else:
                    self.body_splitter.setSizes([min_left, int(self.width() * 0.66), 0])
            if show_right and self.viz_overlay.isVisible():
                self.viz_overlay.hide()
            self.top_bar.set_cross_active(show_right)
            return

        self.right_col.setVisible(False)

        if self._layout_mode == "medium":
            self.left_col.setVisible(True)
            self.center_col.setVisible(True)
            self.center_col.set_compact_back_enabled(False)
            self.act_back.setEnabled(False)
            if mode_changed:
                min_left = max(self.left_col.minimumWidth(), int(self.width() * 0.38))
                self.body_splitter.setSizes([min_left, int(self.width() * 0.62), 0])
            self.top_bar.set_cross_active(self.viz_overlay.isVisible())
            return

        if self._compact_view == "detail" and has_selection:
            self.left_col.setVisible(False)
            self.center_col.setVisible(True)
            self.center_col.set_compact_back_enabled(True)
            self.act_back.setEnabled(True)
        else:
            self._compact_view = "list"
            self.left_col.setVisible(True)
            self.center_col.setVisible(False)
            self.center_col.set_compact_back_enabled(False)
            self.act_back.setEnabled(False)
        if mode_changed:
            self.body_splitter.setSizes([760, 0, 0])
        self.top_bar.set_cross_active(self.viz_overlay.isVisible())

    def _handle_cross_section_request(self) -> None:
        if self._layout_mode == "wide":
            self._right_column_enabled = not self._right_column_enabled
            self.left_col._update_minimum_width()
            self._apply_responsive_layout()
            self.left_col.refresh(self._selected_step_id)
            return
        self._open_viz_overlay()

    def _open_viz_overlay(self) -> None:
        if self.viz_overlay.isVisible():
            self.viz_overlay.hide()
            self.top_bar.set_cross_active(False)
            return
        self.viz_overlay.resize(max(760, int(self.width() * 0.82)), max(560, int(self.height() * 0.84)))
        self.viz_overlay.set_state(self.engine.current_state)
        self.viz_overlay.show()
        self.viz_overlay.raise_()
        self.viz_overlay.activateWindow()
        self.top_bar.set_cross_active(True)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._apply_responsive_layout()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        self._apply_responsive_layout()
        super().showEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.PaletteChange and not self._palette_refresh_guard:
            self._schedule_palette_refresh()
        super().changeEvent(event)

    def _schedule_palette_refresh(self) -> None:
        if self._palette_refresh_scheduled:
            return
        self._palette_refresh_scheduled = True
        QTimer.singleShot(0, self._apply_palette_refresh)

    def _apply_palette_refresh(self) -> None:
        if self._palette_refresh_guard:
            return
        self._palette_refresh_scheduled = False
        self._palette_refresh_guard = True
        try:
            # Re-apply styles and repaint visible components without rebuilding full list models.
            self._apply_style_sheet()
            self.center_col._apply_theme_styles()
            self.left_col._apply_active_markers()
            self.left_col.list.viewport().update()
            self.cross_card.canvas.update()
            self.artifacts_card.update()
            if self.viz_overlay.isVisible():
                self.viz_overlay.cross.canvas.update()
                self.viz_overlay.artifacts.update()
            if self._layout_mode == "wide":
                self.top_bar.set_cross_active(self.right_col.isVisible())
            else:
                self.top_bar.set_cross_active(self.viz_overlay.isVisible())
            self.update()
        finally:
            self._palette_refresh_guard = False

    def _apply_style_sheet(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: palette(window);
            }
            #TopBar {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 14px;
            }
            #LogoBadge {
                background: palette(highlight);
                color: palette(highlighted-text);
                border-radius: 8px;
                font-weight: 700;
            }
            #BrandText {
                font-size: 18px;
                font-weight: 700;
                color: palette(text);
            }
            #Card {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 16px;
            }
            #ColumnTitle {
                color: palette(text);
                font-weight: 700;
            }
            #MutedText {
                color: palette(text);
            }
            #SearchBox, #StatusFilter {
                border: 1px solid palette(mid);
                border-radius: 10px;
                background: palette(base);
                padding: 4px 8px;
                min-height: 24px;
            }
            #ProcessList {
                background: transparent;
            }
            #ProcessItem {
                background: palette(base);
                border: 1px solid palette(midlight);
                border-radius: 12px;
            }
            #ProcessItem[active="true"] {
                background: palette(alternate-base);
                border: 1px solid palette(highlight);
            }
            #DragGrabber {
                color: palette(text);
                font-weight: 600;
            }
            #StepNumber {
                color: palette(text);
            }
            #ProcessName {
                color: palette(text);
                font-weight: 700;
            }
            #ProcessParams {
                color: palette(text);
            }
            #TopButton, #RowActionButton, #PrimaryActionButton, #SecondaryActionButton, #BackLink {
                border-radius: 10px;
                padding: 5px 10px;
                background: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
            }
            #TopButton:hover, #RowActionButton:hover, #PrimaryActionButton:hover, #SecondaryActionButton:hover, #BackLink:hover {
                border: 1px solid palette(highlight);
                background: palette(alternate-base);
            }
            #TopButton:checked {
                border: 1px solid palette(highlight);
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            #TopButton[active="true"] {
                border: 1px solid palette(highlight);
                background: palette(alternate-base);
            }
            #RowActionButton[action_state="run_now"] {
                background: palette(highlight);
                color: palette(highlighted-text);
                border: 1px solid palette(highlight);
            }
            #RowActionButton[action_state="run_now"]:hover {
                background: palette(highlight);
                color: palette(highlighted-text);
                border: 1px solid palette(highlight);
            }
            #RowActionButton[action_state="pending"] {
                background: palette(alternate-base);
                color: palette(text);
                border: 1px solid palette(mid);
            }
            #RowActionButton[action_state="done"] {
                background: #2e7d32;
                color: #ffffff;
                border: 1px solid #2e7d32;
            }
            #RowActionButton[action_state="done"]:disabled {
                background: #2e7d32;
                color: #ffffff;
                border: 1px solid #2e7d32;
            }
            #RowActionButton[action_state="running"], #RowActionButton[action_state="pending"]:disabled {
                background: palette(alternate-base);
                color: palette(text);
                border: 1px solid palette(mid);
            }
            #DeleteStepButton {
                border-radius: 10px;
                background: #b42318;
                color: #ffffff;
                border: 1px solid #912018;
                padding: 5px 10px;
                font-weight: 600;
            }
            #DeleteStepButton:hover {
                background: #c7362b;
                border: 1px solid #c7362b;
            }
            #InsertStepButton {
                background: transparent;
                border: none;
                color: palette(highlight);
                font-weight: 700;
                font-size: 18px;
                padding: 0px;
            }
            #InsertStepButton[hovered="true"] {
                background: palette(highlight);
                color: palette(highlighted-text);
                border: 1px solid palette(highlight);
                border-radius: 13px;
            }
            #ArtifactItem {
                background: palette(alternate-base);
                border: 1px solid palette(mid);
                border-radius: 12px;
            }
            #ArtifactSummary {
                color: palette(text);
                font-weight: 600;
            }
            #TopId {
                color: palette(text);
                font-weight: 600;
            }
            #SystemDot {
                border-radius: 5px;
                background: #2e7d32;
                border: 1px solid #2e7d32;
            }
            """
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} v{APP_VERSION}")
    app.setOrganizationName("NanoFab")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

