"""
Windrose Save Recovery Tool – Main Window (PySide6)

Layout:
  ┌─────────────────────────────────────────────────────┐
  │  Header bar (logo + title)                          │
  ├───────────────────┬─────────────────────────────────┤
  │  Left panel       │  Right panel                    │
  │  • Folder picker  │  • Diagnostics log              │
  │  • World list     │  • Color-coded issues           │
  │  • Action buttons │                                 │
  └───────────────────┴─────────────────────────────────┘
"""

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QThread, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QPalette, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QListWidget, QListWidgetItem,
    QTextEdit, QSplitter, QFrame, QMessageBox, QProgressBar, QComboBox,
    QGroupBox, QSizePolicy,
)

from core import (
    validate_save, create_backup, recover_save,
    find_save_roots, default_windrose_root, list_backups,
)
from models.results import Severity

log = logging.getLogger("windrose.ui")

# ---------------------------------------------------------------------------
# Color palette (dark theme)
# ---------------------------------------------------------------------------
COLORS = {
    "bg":         "#0e0f13",
    "surface":    "#181a22",
    "border":     "#2a2d3a",
    "text":       "#dde1f0",
    "muted":      "#6b7094",
    "ok":         "#4caf82",
    "warning":    "#e6a817",
    "error":      "#e05050",
    "critical":   "#c0392b",
    "accent":     "#5b8df5",
    "accent2":    "#8b5cf6",
    "header_bg":  "#12141d",
}

SEV_COLORS = {
    Severity.OK:       COLORS["ok"],
    Severity.WARNING:  COLORS["warning"],
    Severity.ERROR:    COLORS["error"],
    Severity.CRITICAL: COLORS["critical"],
}


# ---------------------------------------------------------------------------
# Worker signals (thread-safe bridge to the GUI)
# ---------------------------------------------------------------------------
class WorkerSignals(QObject):
    log_line   = Signal(str, str)   # (message, color)
    done       = Signal(bool, str)  # (success, summary)


class Worker(QThread):
    """Runs blocking core operations off the GUI thread."""

    def __init__(self, task: str, folder: Path, backup_src: Path | None = None):
        super().__init__()
        self.task = task
        self.folder = folder
        self.backup_src = backup_src
        self.signals = WorkerSignals()

    def _emit(self, msg: str, color: str = COLORS["text"]):
        self.signals.log_line.emit(msg, color)

    def run(self):
        try:
            if self.task == "validate":
                self._run_validate()
            elif self.task == "repair":
                self._run_repair()
            elif self.task == "restore":
                self._run_restore()
        except Exception as exc:  # noqa: BLE001
            self._emit(f"Unexpected error: {exc}", COLORS["critical"])
            self.signals.done.emit(False, str(exc))

    def _run_validate(self):
        self._emit(f"─── Validating: {self.folder.name} ───", COLORS["accent"])
        result = validate_save(self.folder)
        for issue in result.issues:
            color = SEV_COLORS.get(issue.severity, COLORS["text"])
            tag = issue.severity.value.upper()
            self._emit(f"  [{tag}] {issue.message}", color)
            if issue.detail:
                self._emit(f"          {issue.detail}", COLORS["muted"])

        if result.rocksdb_readable:
            self._emit("  RocksDB open test: PASSED ✓", COLORS["ok"])
        else:
            self._emit("  RocksDB open test: FAILED ✗", COLORS["error"])

        summary = "healthy" if result.healthy else "issues detected"
        self._emit(f"─── Done: {summary} ───", COLORS["accent"])
        self.signals.done.emit(result.healthy, summary)

    def _run_repair(self):
        self._emit(f"─── Repairing: {self.folder.name} ───", COLORS["accent2"])
        self._emit("  Creating backup…", COLORS["muted"])
        try:
            bk = create_backup(self.folder)
            self._emit(f"  Backup created: {bk}", COLORS["ok"])
        except RuntimeError as exc:
            self._emit(f"  Backup FAILED: {exc}", COLORS["critical"])
            self.signals.done.emit(False, "Backup failed – repair aborted")
            return

        self._emit("  Running recovery…", COLORS["muted"])
        res = recover_save(self.folder)
        for op in res.operations:
            color = COLORS["ok"] if "PASSED" in op or "success" in op.lower() else COLORS["text"]
            self._emit(f"  • {op}", color)

        if res.error:
            self._emit(f"  Error: {res.error}", COLORS["error"])

        if res.recovered_path:
            self._emit(f"  Output: {res.recovered_path}", COLORS["accent"])

        self.signals.done.emit(res.success, "Recovery complete" if res.success else "Recovery incomplete")

    def _run_restore(self):
        if not self.backup_src:
            self.signals.done.emit(False, "No backup selected")
            return
        self._emit(f"─── Restoring from backup ───", COLORS["accent2"])
        self._emit(f"  Source: {self.backup_src}", COLORS["muted"])
        # Restoration = recovery with explicit backup source.
        try:
            bk = create_backup(self.folder)
            self._emit(f"  Safety backup: {bk}", COLORS["ok"])
        except RuntimeError as exc:
            self._emit(f"  Safety backup failed: {exc} – continuing anyway", COLORS["warning"])

        res = recover_save(self.folder, backup_source=self.backup_src)
        for op in res.operations:
            self._emit(f"  • {op}")
        self.signals.done.emit(res.success, "Restore complete" if res.success else "Restore failed")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Windrose Save Recovery Tool")
        self.setMinimumSize(1000, 680)
        self._worker: Worker | None = None
        self._selected_folder: Path | None = None
        self._worlds: list[Path] = []

        self._apply_stylesheet()
        self._build_ui()
        self._setup_logging()
        self._try_autodetect()

    # -----------------------------------------------------------------------
    # Stylesheet
    # -----------------------------------------------------------------------
    def _apply_stylesheet(self):
        c = COLORS
        self.setStyleSheet(f"""
        QMainWindow, QWidget {{
            background: {c['bg']};
            color: {c['text']};
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 13px;
        }}
        QGroupBox {{
            border: 1px solid {c['border']};
            border-radius: 6px;
            margin-top: 10px;
            padding: 8px;
            font-weight: bold;
            color: {c['muted']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }}
        QPushButton {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 5px;
            padding: 7px 14px;
            color: {c['text']};
            font-weight: bold;
        }}
        QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
        QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border']}; }}
        QPushButton#repair {{ border-color: {c['accent2']}; }}
        QPushButton#repair:hover {{ background: {c['accent2']}22; color: {c['accent2']}; }}
        QPushButton#analyze {{ border-color: {c['accent']}; }}
        QPushButton#analyze:hover {{ background: {c['accent']}22; }}
        QListWidget {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 5px;
            padding: 4px;
        }}
        QListWidget::item:selected {{
            background: {c['accent']}44;
            color: {c['text']};
        }}
        QListWidget::item:hover {{ background: {c['border']}; }}
        QTextEdit {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 5px;
            padding: 6px;
            line-height: 1.5;
        }}
        QComboBox {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 4px 8px;
            color: {c['text']};
        }}
        QComboBox QAbstractItemView {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            selection-background-color: {c['accent']}44;
        }}
        QProgressBar {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 3px;
            height: 4px;
            text-align: center;
        }}
        QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
        QSplitter::handle {{ background: {c['border']}; width: 1px; }}
        QLabel#header_title {{
            font-size: 18px;
            font-weight: bold;
            color: {c['text']};
            letter-spacing: 1px;
        }}
        QLabel#status_ok    {{ color: {c['ok']}; font-weight: bold; }}
        QLabel#status_warn  {{ color: {c['warning']}; font-weight: bold; }}
        QLabel#status_err   {{ color: {c['error']}; font-weight: bold; }}
        QLabel#status_idle  {{ color: {c['muted']}; }}
        """)

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([320, 680])
        splitter.setHandleWidth(1)

        layout.addWidget(splitter, 1)
        layout.addWidget(self._build_statusbar())

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(56)
        w.setStyleSheet(f"background: {COLORS['header_bg']}; border-bottom: 1px solid {COLORS['border']};")
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 0, 16, 0)

        # Rune-style icon placeholder (Unicode compass)
        icon = QLabel("⊕")
        icon.setStyleSheet(f"font-size: 28px; color: {COLORS['accent']}; margin-right: 8px;")
        h.addWidget(icon)

        title = QLabel("WINDROSE  SAVE RECOVERY")
        title.setObjectName("header_title")
        h.addWidget(title)
        h.addStretch()

        subtitle = QLabel("v1.0  •  RocksDB Diagnostic & Repair")
        subtitle.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        h.addWidget(subtitle)
        return w

    def _build_left(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(310)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- Folder picker ---
        grp_path = QGroupBox("Save Location")
        gp_layout = QVBoxLayout(grp_path)

        self.lbl_path = QLabel("No folder selected")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        gp_layout.addWidget(self.lbl_path)

        row = QHBoxLayout()
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._on_browse)
        btn_auto = QPushButton("Auto-detect")
        btn_auto.clicked.connect(self._try_autodetect)
        row.addWidget(btn_browse)
        row.addWidget(btn_auto)
        gp_layout.addLayout(row)
        layout.addWidget(grp_path)

        # --- World list ---
        grp_worlds = QGroupBox("Detected Worlds")
        gw_layout = QVBoxLayout(grp_worlds)
        self.world_list = QListWidget()
        self.world_list.currentRowChanged.connect(self._on_world_selected)
        gw_layout.addWidget(self.world_list)
        layout.addWidget(grp_worlds, 1)

        # --- Actions ---
        grp_actions = QGroupBox("Actions")
        ga_layout = QVBoxLayout(grp_actions)

        self.btn_analyze = QPushButton("⚙  Analyze Save")
        self.btn_analyze.setObjectName("analyze")
        self.btn_analyze.clicked.connect(self._on_analyze)
        self.btn_analyze.setEnabled(False)

        self.btn_repair = QPushButton("✦  Repair Save")
        self.btn_repair.setObjectName("repair")
        self.btn_repair.clicked.connect(self._on_repair)
        self.btn_repair.setEnabled(False)

        self.btn_restore = QPushButton("↺  Restore Backup")
        self.btn_restore.clicked.connect(self._on_restore)
        self.btn_restore.setEnabled(False)

        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(self.log_panel.clear if hasattr(self, "log_panel") else lambda: None)
        btn_clear.clicked.connect(lambda: self.log_panel.clear())

        ga_layout.addWidget(self.btn_analyze)
        ga_layout.addWidget(self.btn_repair)
        ga_layout.addWidget(self.btn_restore)
        ga_layout.addWidget(btn_clear)
        layout.addWidget(grp_actions)

        # --- Backup selector ---
        grp_bk = QGroupBox("Available Backups")
        gbk_layout = QVBoxLayout(grp_bk)
        self.backup_combo = QComboBox()
        self.backup_combo.setPlaceholderText("No backups found")
        gbk_layout.addWidget(self.backup_combo)
        layout.addWidget(grp_bk)

        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 12, 12, 8)
        layout.setSpacing(6)

        lbl = QLabel("Diagnostics Output")
        lbl.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px; font-weight: bold;")
        layout.addWidget(lbl)

        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setFont(QFont("Consolas", 12))
        layout.addWidget(self.log_panel, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        layout.addWidget(self.progress)

        return w

    def _build_statusbar(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(28)
        w.setStyleSheet(f"background: {COLORS['header_bg']}; border-top: 1px solid {COLORS['border']};")
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 0, 12, 0)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status_idle")
        h.addWidget(self.status_label)
        h.addStretch()

        self.world_status = QLabel("")
        self.world_status.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        h.addWidget(self.world_status)
        return w

    # -----------------------------------------------------------------------
    # Logging bridge (Python logging → log panel)
    # -----------------------------------------------------------------------
    def _setup_logging(self):
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            handlers=[
                logging.FileHandler("logs/recovery.log", encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )

    def _append_log(self, text: str, color: str = COLORS["text"]):
        cursor = self.log_panel.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text + "\n", fmt)
        self.log_panel.setTextCursor(cursor)
        self.log_panel.ensureCursorVisible()

    # -----------------------------------------------------------------------
    # Folder / world logic
    # -----------------------------------------------------------------------
    def _try_autodetect(self):
        from core.rocksdb_utils import default_windrose_root
        root = default_windrose_root()
        if root:
            self._load_save_root(root)
        else:
            self._append_log("Auto-detect: Windrose save folder not found on this machine.",
                             COLORS["muted"])

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Windrose Save Folder")
        if folder:
            self._load_save_root(Path(folder))

    def _load_save_root(self, root: Path):
        self.lbl_path.setText(str(root))
        worlds = find_save_roots(root)
        if not worlds:
            # Maybe user selected a single world folder directly.
            if any(root.glob("MANIFEST-*")) or (root / "CURRENT").exists():
                worlds = [root]

        self.world_list.clear()
        self._worlds = worlds
        for w in worlds:
            item = QListWidgetItem(w.name)
            item.setData(Qt.UserRole, w)
            self.world_list.addItem(item)

        if worlds:
            self.world_list.setCurrentRow(0)
            self._append_log(f"Found {len(worlds)} world(s) in {root}", COLORS["ok"])
        else:
            self._append_log(f"No RocksDB world folders detected under {root}", COLORS["warning"])

    def _on_world_selected(self, row: int):
        if row < 0:
            return
        self._selected_folder = self._worlds[row]
        self.btn_analyze.setEnabled(True)
        self.btn_repair.setEnabled(True)
        self.world_status.setText(str(self._selected_folder))
        self._refresh_backups()

    def _refresh_backups(self):
        self.backup_combo.clear()
        if not self._selected_folder:
            return
        backups = list_backups(self._selected_folder)
        for b in backups:
            # Display the timestamp from parent folder name.
            ts = b.parent.name
            self.backup_combo.addItem(ts, userData=b)
        self.btn_restore.setEnabled(bool(backups))
        if not backups:
            self._append_log("  No backups found for this world.", COLORS["muted"])

    # -----------------------------------------------------------------------
    # Worker dispatch
    # -----------------------------------------------------------------------
    def _start_worker(self, task: str, backup_src: Path | None = None):
        if self._worker and self._worker.isRunning():
            return
        if not self._selected_folder:
            return

        self.progress.setVisible(True)
        self._set_buttons_enabled(False)
        self.status_label.setText(f"Running: {task}…")
        self.status_label.setObjectName("status_idle")

        self._worker = Worker(task, self._selected_folder, backup_src)
        self._worker.signals.log_line.connect(self._append_log)
        self._worker.signals.done.connect(self._on_worker_done)
        self._worker.start()

    def _on_worker_done(self, success: bool, summary: str):
        self.progress.setVisible(False)
        self._set_buttons_enabled(True)
        color = COLORS["ok"] if success else COLORS["error"]
        obj_name = "status_ok" if success else "status_err"
        self.status_label.setText(summary)
        self.status_label.setObjectName(obj_name)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._refresh_backups()

    def _set_buttons_enabled(self, state: bool):
        self.btn_analyze.setEnabled(state and self._selected_folder is not None)
        self.btn_repair.setEnabled(state and self._selected_folder is not None)
        self.btn_restore.setEnabled(state and self.backup_combo.count() > 0)

    # -----------------------------------------------------------------------
    # Button handlers
    # -----------------------------------------------------------------------
    def _on_analyze(self):
        self._append_log("")
        self._start_worker("validate")

    def _on_repair(self):
        self._append_log("")
        confirm = QMessageBox.question(
            self, "Confirm Repair",
            "A backup will be created automatically before any changes.\n\n"
            "Repairs are written to a _Recovered copy; your original save is NOT modified.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self._start_worker("repair")

    def _on_restore(self):
        idx = self.backup_combo.currentIndex()
        if idx < 0:
            return
        backup_path: Path = self.backup_combo.itemData(idx)
        confirm = QMessageBox.question(
            self, "Confirm Restore",
            f"Restore from backup:\n  {backup_path}\n\n"
            "A safety backup of the current state will be made first.\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self._start_worker("restore", backup_src=backup_path)
