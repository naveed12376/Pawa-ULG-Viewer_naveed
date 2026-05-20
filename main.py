"""ULG (PX4 ULog) File Viewer — PyQt6 edition.

A modern, dark-themed GUI for browsing and plotting ULog files.
Favorites are persisted to settings.txt in the workspace.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QPalette, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QLabel, QLineEdit,
    QFileDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QSplitter,
    QVBoxLayout, QHBoxLayout, QFrame, QMenu, QStatusBar, QToolButton,
    QSizePolicy, QStyle,
)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

try:
    from pyulog import ULog
except ImportError:
    print("Missing dependency: pyulog. Install it via:  pip install pyulog matplotlib PyQt6")
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.txt")


# Modern dark palette - inspired by Material / VSCode dark themes
COLORS = {
    "bg":        "#1e1f29",
    "bg_alt":    "#282a36",
    "panel":     "#21222c",
    "border":    "#3a3d4d",
    "text":      "#f8f8f2",
    "text_dim":  "#9a9bb0",
    "accent":    "#bd93f9",   # purple
    "accent_2":  "#8be9fd",   # cyan
    "success":   "#50fa7b",   # green
    "warn":      "#ffb86c",   # orange
    "danger":    "#ff5555",   # red
    "muted":     "#44475a",
}

# Matplotlib dark style applied to the embedded figure
PLT_BG = COLORS["panel"]
PLT_FG = COLORS["text"]
PLT_GRID = COLORS["muted"]
MPL_COLOR_CYCLE = [
    "#8be9fd", "#50fa7b", "#ffb86c", "#ff79c6",
    "#bd93f9", "#f1fa8c", "#ff5555", "#6272a4",
]

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 10pt;
}}

QLabel#Header {{
    font-size: 11pt;
    font-weight: 600;
    color: {COLORS['text']};
    padding: 2px 0 6px 2px;
}}
QLabel#SubHeader {{
    font-size: 9pt;
    font-weight: 600;
    color: {COLORS['text_dim']};
    letter-spacing: 1px;
    padding: 2px 0 4px 2px;
}}
QLabel#FileLabel {{
    color: {COLORS['accent_2']};
    font-style: italic;
}}
QLabel#StatusLabel {{
    color: {COLORS['text_dim']};
    padding: 4px 10px;
}}

QFrame#Card {{
    background-color: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px;
}}

QFrame#TopBar {{
    background-color: {COLORS['bg_alt']};
    border-bottom: 1px solid {COLORS['border']};
}}

QPushButton {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {COLORS['muted']};
    border-color: {COLORS['accent']};
}}
QPushButton:pressed {{
    background-color: {COLORS['border']};
}}
QPushButton#Primary {{
    background-color: {COLORS['accent']};
    color: #1e1f29;
    border: 1px solid {COLORS['accent']};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background-color: #cda6ff;
    border-color: #cda6ff;
}}
QPushButton#Danger {{
    color: {COLORS['danger']};
    border-color: {COLORS['border']};
}}
QPushButton#Danger:hover {{
    background-color: rgba(255, 85, 85, 0.15);
    border-color: {COLORS['danger']};
}}

QLineEdit {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus {{
    border-color: {COLORS['accent_2']};
}}

QTreeWidget {{
    background-color: {COLORS['panel']};
    alternate-background-color: {COLORS['bg_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    outline: 0;
    padding: 4px;
    color: {COLORS['text']};
}}
QTreeWidget::item {{
    padding: 4px 4px;
    border-radius: 4px;
}}
QTreeWidget::item:hover {{
    background-color: {COLORS['muted']};
}}
QTreeWidget::item:selected {{
    background-color: {COLORS['accent']};
    color: #1e1f29;
}}
QTreeWidget::branch {{
    background: transparent;
}}

QHeaderView::section {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['text_dim']};
    border: none;
    padding: 6px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['muted']};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['accent']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background-color: {COLORS['muted']};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['accent']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QSplitter::handle {{
    background-color: {COLORS['border']};
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QSplitter::handle:vertical {{
    height: 3px;
}}
QSplitter::handle:hover {{
    background-color: {COLORS['accent']};
}}

QMenu {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {COLORS['accent']};
    color: #1e1f29;
}}

QStatusBar {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['text_dim']};
    border-top: 1px solid {COLORS['border']};
}}

QToolBar {{
    background-color: {COLORS['bg_alt']};
    border: none;
    spacing: 2px;
}}
QToolButton {{
    background-color: transparent;
    color: {COLORS['text']};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
}}
QToolButton:hover {{
    background-color: {COLORS['muted']};
    border-color: {COLORS['border']};
}}
QToolButton:checked {{
    background-color: {COLORS['accent']};
    color: #1e1f29;
}}
"""


class ULGViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ULG Data Viewer")
        self.resize(1380, 860)
        self.setMinimumSize(1000, 640)

        self.ulog = None
        self.current_file: str | None = None
        self.datasets: Dict[str, object] = {}
        self.favorites: List[Tuple[str, str]] = self._load_favorites()

        self._apply_mpl_style()
        self._build_ui()
        self._refresh_favorites_tree()
        self._draw_empty_message("Load a ULG file and select fields to plot.")

    # ------------------------ Matplotlib style ------------------------ #
    def _apply_mpl_style(self):
        matplotlib.rcParams.update({
            "figure.facecolor": PLT_BG,
            "axes.facecolor":   PLT_BG,
            "savefig.facecolor": PLT_BG,
            "axes.edgecolor":   COLORS["border"],
            "axes.labelcolor":  PLT_FG,
            "axes.titlecolor":  PLT_FG,
            "axes.titlesize":   10,
            "axes.titleweight": "bold",
            "axes.grid":        True,
            "grid.color":       PLT_GRID,
            "grid.alpha":       0.35,
            "grid.linestyle":   "-",
            "xtick.color":      PLT_FG,
            "ytick.color":      PLT_FG,
            "text.color":       PLT_FG,
            "legend.facecolor": COLORS["bg_alt"],
            "legend.edgecolor": COLORS["border"],
            "legend.labelcolor": PLT_FG,
            "legend.fontsize":  8,
            "axes.prop_cycle":  matplotlib.cycler(color=MPL_COLOR_CYCLE),
            "lines.linewidth":  1.1,
        })

    # ------------------------------ UI ------------------------------ #
    def _icon(self, sp: QStyle.StandardPixmap) -> QIcon:
        return self.style().standardIcon(sp)

    def _build_ui(self):
        self.setStatusBar(QStatusBar())
        self._set_status("Ready. Click 'Browse ULG File…' to begin.")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -------- Top bar --------
        top = QFrame(objectName="TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(10)

        title = QLabel("ULG Data Viewer")
        title.setObjectName("Header")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)

        self.browse_btn = QPushButton("  Browse ULG File…")
        self.browse_btn.setObjectName("Primary")
        self.browse_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.browse_btn.setIconSize(QSize(16, 16))
        self.browse_btn.clicked.connect(self.browse_file)

        self.file_label = QLabel("No file loaded")
        self.file_label.setObjectName("FileLabel")

        self.plot_btn = QPushButton("  Plot Selected")
        self.plot_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaPlay))
        self.plot_btn.clicked.connect(self.plot_selected)

        self.plot_all_btn = QPushButton("  Plot All (Overview)")
        self.plot_all_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.plot_all_btn.clicked.connect(self.plot_all_overview)

        self.clear_btn = QPushButton("  Clear Plot")
        self.clear_btn.setObjectName("Danger")
        self.clear_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_DialogResetButton))
        self.clear_btn.clicked.connect(self.clear_plot)

        top_layout.addWidget(title)
        top_layout.addSpacing(20)
        top_layout.addWidget(self.browse_btn)
        top_layout.addWidget(self.file_label, stretch=1)
        top_layout.addWidget(self.clear_btn)
        top_layout.addWidget(self.plot_all_btn)
        top_layout.addWidget(self.plot_btn)

        root.addWidget(top)

        # -------- Main horizontal splitter --------
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setContentsMargins(0, 0, 0, 0)
        main_split.setHandleWidth(3)

        # ----- Left side: vertical splitter (favorites on top, topics below) -----
        left_split = QSplitter(Qt.Orientation.Vertical)
        left_split.setHandleWidth(3)

        # Favorites card
        fav_card = QFrame(objectName="Card")
        fav_v = QVBoxLayout(fav_card)
        fav_v.setContentsMargins(10, 10, 10, 10)
        fav_v.setSpacing(6)

        fav_header_row = QHBoxLayout()
        fav_title = QLabel("★  FAVORITES")
        fav_title.setObjectName("SubHeader")
        fav_title.setStyleSheet(f"color: {COLORS['warn']}; letter-spacing: 1.5px;")
        fav_header_row.addWidget(fav_title)
        fav_header_row.addStretch(1)

        self.fav_remove_btn = QPushButton("Remove")
        self.fav_remove_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_TrashIcon))
        self.fav_remove_btn.clicked.connect(self.remove_selected_favorite)
        fav_header_row.addWidget(self.fav_remove_btn)
        fav_v.addLayout(fav_header_row)

        self.fav_tree = QTreeWidget()
        self.fav_tree.setHeaderHidden(True)
        self.fav_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.fav_tree.setAlternatingRowColors(False)
        self.fav_tree.setRootIsDecorated(False)
        self.fav_tree.itemDoubleClicked.connect(lambda *_: self.plot_selected())
        self.fav_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fav_tree.customContextMenuRequested.connect(self._on_fav_context_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.fav_tree,
                  activated=self.remove_selected_favorite)
        fav_v.addWidget(self.fav_tree)

        left_split.addWidget(fav_card)

        # Topics card
        topics_card = QFrame(objectName="Card")
        topics_v = QVBoxLayout(topics_card)
        topics_v.setContentsMargins(10, 10, 10, 10)
        topics_v.setSpacing(6)

        topics_title = QLabel("TOPICS & FIELDS")
        topics_title.setObjectName("SubHeader")
        topics_v.addWidget(topics_title)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍  Filter topics or fields…")
        self.search_input.textChanged.connect(self._apply_filter)
        topics_v.addWidget(self.search_input)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.plot_selected())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        topics_v.addWidget(self.tree)

        left_split.addWidget(topics_card)
        left_split.setSizes([220, 560])

        main_split.addWidget(left_split)

        # ----- Right side: plot card -----
        plot_card = QFrame(objectName="Card")
        plot_v = QVBoxLayout(plot_card)
        plot_v.setContentsMargins(10, 10, 10, 10)
        plot_v.setSpacing(6)

        plot_title = QLabel("PLOT")
        plot_title.setObjectName("SubHeader")
        plot_v.addWidget(plot_title)

        self.figure = Figure(figsize=(9, 6), dpi=100, facecolor=PLT_BG)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_v.addWidget(self.toolbar)
        plot_v.addWidget(self.canvas, stretch=1)

        main_split.addWidget(plot_card)
        main_split.setSizes([380, 1000])

        # Wrap in margin
        outer = QWidget()
        outer_l = QHBoxLayout(outer)
        outer_l.setContentsMargins(10, 10, 10, 10)
        outer_l.addWidget(main_split)
        root.addWidget(outer, stretch=1)

    def _set_status(self, msg: str):
        self.statusBar().showMessage(msg)

    # -------------------- Context menus -------------------- #
    def _on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if item not in self.tree.selectedItems():
            self.tree.setCurrentItem(item)

        menu = QMenu(self)
        add_action = QAction("★  Add to Favorites", self)
        add_action.triggered.connect(self.add_selected_to_favorites)
        plot_action = QAction("▶  Plot", self)
        plot_action.triggered.connect(self.plot_selected)
        menu.addAction(add_action)
        menu.addSeparator()
        menu.addAction(plot_action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_fav_context_menu(self, pos):
        item = self.fav_tree.itemAt(pos)
        if item is None:
            return
        if item not in self.fav_tree.selectedItems():
            self.fav_tree.setCurrentItem(item)

        menu = QMenu(self)
        remove = QAction("🗑  Remove from Favorites", self)
        remove.triggered.connect(self.remove_selected_favorite)
        plot_action = QAction("▶  Plot", self)
        plot_action.triggered.connect(self.plot_selected)
        menu.addAction(plot_action)
        menu.addSeparator()
        menu.addAction(remove)
        menu.exec(self.fav_tree.viewport().mapToGlobal(pos))

    # -------------------- Favorites I/O -------------------- #
    def _load_favorites(self) -> List[Tuple[str, str]]:
        favs: List[Tuple[str, str]] = []
        if not os.path.isfile(SETTINGS_FILE):
            return favs
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "|" not in line:
                        continue
                    topic, field = line.split("|", 1)
                    topic, field = topic.strip(), field.strip()
                    if topic and field and (topic, field) not in favs:
                        favs.append((topic, field))
        except Exception as e:
            print(f"Warning: could not read {SETTINGS_FILE}: {e}")
        return favs

    def _save_favorites(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                f.write("# ULG Viewer favorites — one per line as: topic|field\n")
                for topic, field in self.favorites:
                    f.write(f"{topic}|{field}\n")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not write {SETTINGS_FILE}:\n{e}")

    def add_selected_to_favorites(self):
        added = 0
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            topic, field = data
            if field is None:
                dset = self.datasets.get(topic)
                if not dset:
                    continue
                for f in sorted(dset.data.keys()):
                    if f == "timestamp":
                        continue
                    if (topic, f) not in self.favorites:
                        self.favorites.append((topic, f))
                        added += 1
            else:
                if (topic, field) not in self.favorites:
                    self.favorites.append((topic, field))
                    added += 1
        if added:
            self._save_favorites()
            self._refresh_favorites_tree()
            self._set_status(f"Added {added} favorite(s).")
        else:
            self._set_status("Selected item(s) already in favorites.")

    def remove_selected_favorite(self):
        to_remove = []
        for item in self.fav_tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                to_remove.append(tuple(data))
        if not to_remove:
            return
        self.favorites = [fv for fv in self.favorites if fv not in to_remove]
        self._save_favorites()
        self._refresh_favorites_tree()
        self._set_status(f"Removed {len(to_remove)} favorite(s).")

    def _refresh_favorites_tree(self):
        self.fav_tree.clear()
        for topic, field in self.favorites:
            missing = bool(self.ulog) and (
                topic not in self.datasets or field not in self.datasets[topic].data
            )
            label = f"{topic}  ·  {field}"
            if missing:
                label += "   [not in file]"
            it = QTreeWidgetItem([label])
            it.setData(0, Qt.ItemDataRole.UserRole, (topic, field))
            if missing:
                it.setForeground(0, QColor(COLORS["text_dim"]))
            else:
                it.setForeground(0, QColor(COLORS["warn"]))
            self.fav_tree.addTopLevelItem(it)

    # -------------------- File loading -------------------- #
    def browse_file(self):
        initial_dir = os.path.join(SCRIPT_DIR, "data")
        if not os.path.isdir(initial_dir):
            initial_dir = SCRIPT_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a ULG File", initial_dir,
            "ULog files (*.ulg);;All files (*)",
        )
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        self._set_status(f"Loading {os.path.basename(path)}…")
        QApplication.processEvents()
        try:
            ulog = ULog(path)
        except Exception as e:
            QMessageBox.critical(self, "Failed to load ULG", f"Could not load file:\n{e}")
            self._set_status("Load failed.")
            return

        self.ulog = ulog
        self.current_file = path
        self.datasets = {
            d.name + (f"_{d.multi_id}" if d.multi_id else ""): d for d in ulog.data_list
        }
        self.file_label.setText(f"📄  {os.path.basename(path)}")
        self._populate_tree()
        self._refresh_favorites_tree()
        self._draw_empty_message("Pick fields from Favorites or Topics, then click Plot Selected.")

        n_topics = len(self.datasets)
        n_fields = sum(len(d.data) - 1 for d in self.datasets.values())
        self._set_status(
            f"Loaded {os.path.basename(path)}   ·   "
            f"{n_topics} topics, ~{n_fields} numeric fields."
        )

    # -------------------- Tree population -------------------- #
    def _populate_tree(self, query: str = ""):
        self.tree.clear()
        query = query.strip().lower()

        for topic_name in sorted(self.datasets.keys()):
            dset = self.datasets[topic_name]
            all_fields = [f for f in sorted(dset.data.keys()) if f != "timestamp"]

            topic_match = (not query) or (query in topic_name.lower())
            matching_fields = (
                all_fields if topic_match
                else [f for f in all_fields if query in f.lower()]
            )
            if not matching_fields and not topic_match:
                continue
            fields_to_show = matching_fields if (matching_fields or topic_match) else all_fields

            n_samples = len(next(iter(dset.data.values()))) if dset.data else 0
            top = QTreeWidgetItem([f"{topic_name}    ({n_samples} samples)"])
            top.setData(0, Qt.ItemDataRole.UserRole, (topic_name, None))
            top.setForeground(0, QColor(COLORS["accent_2"]))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)

            for f in fields_to_show:
                ch = QTreeWidgetItem([f])
                ch.setData(0, Qt.ItemDataRole.UserRole, (topic_name, f))
                top.addChild(ch)

            self.tree.addTopLevelItem(top)
            if query:
                top.setExpanded(True)

    def _apply_filter(self, text: str):
        self._populate_tree(text)

    # ------------------------- Plotting ------------------------- #
    @staticmethod
    def _topic_time_seconds(dset):
        ts = dset.data.get("timestamp")
        if ts is None or len(ts) == 0:
            return None
        return (ts - ts[0]) / 1e6

    def _draw_empty_message(self, msg: str):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, msg, ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color=COLORS["text_dim"])
        ax.set_axis_off()
        ax.set_facecolor(PLT_BG)
        self.canvas.draw_idle()

    def clear_plot(self):
        self._draw_empty_message("Plot cleared.")
        self._set_status("Plot cleared.")

    def _collect_selection(self) -> Dict[str, set]:
        by_topic: Dict[str, set] = {}

        for item in self.fav_tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            topic, field = data
            if topic in self.datasets and field in self.datasets[topic].data:
                by_topic.setdefault(topic, set()).add(field)

        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            topic, field = data
            if field is None:
                dset = self.datasets.get(topic)
                if not dset:
                    continue
                for f in dset.data.keys():
                    if f != "timestamp":
                        by_topic.setdefault(topic, set()).add(f)
            else:
                by_topic.setdefault(topic, set()).add(field)

        return by_topic

    def _style_axes(self, ax):
        for spine in ax.spines.values():
            spine.set_color(COLORS["border"])
        ax.tick_params(colors=PLT_FG, labelsize=8)
        ax.grid(True, color=PLT_GRID, alpha=0.35)
        ax.set_facecolor(PLT_BG)

    def plot_selected(self):
        if not self.ulog:
            QMessageBox.information(self, "No file", "Load a ULG file first.")
            return
        by_topic = self._collect_selection()
        if not by_topic:
            QMessageBox.information(self, "Nothing selected",
                                    "Select one or more entries in Favorites or Topics & Fields.")
            return

        self.figure.clear()
        topics_sorted = sorted(by_topic.keys())
        n = len(topics_sorted)

        for idx, topic in enumerate(topics_sorted, start=1):
            ax = self.figure.add_subplot(n, 1, idx)
            self._style_axes(ax)
            dset = self.datasets[topic]
            t = self._topic_time_seconds(dset)
            if t is None:
                continue
            fields = sorted(by_topic[topic])
            for f in fields:
                y = dset.data.get(f)
                if y is None:
                    continue
                ax.plot(t, y, label=f, linewidth=1.1)
            ax.set_title(topic, color=COLORS["accent_2"], fontsize=10, fontweight="bold", loc="left")
            ax.set_ylabel("value", fontsize=8)
            if len(fields) <= 12:
                leg = ax.legend(loc="best", fontsize=8, framealpha=0.85)
                if leg:
                    leg.get_frame().set_edgecolor(COLORS["border"])
            if idx == n:
                ax.set_xlabel("time [s]", fontsize=9)

        self.figure.tight_layout()
        self.canvas.draw_idle()
        self._set_status(f"Plotted {n} topic(s).")

    def plot_all_overview(self):
        if not self.ulog:
            QMessageBox.information(self, "No file", "Load a ULG file first.")
            return
        topics = [t for t in sorted(self.datasets.keys())
                  if self._topic_time_seconds(self.datasets[t]) is not None
                  and any(f != "timestamp" for f in self.datasets[t].data.keys())]
        if not topics:
            return
        reply = QMessageBox.question(
            self, "Plot all topics?",
            f"This will draw one subplot per topic ({len(topics)} subplots) on a single figure.\n"
            "It may be cramped and slow to render. Continue?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_status("Plotting all topics…")
        QApplication.processEvents()

        self.figure.clear()
        n = len(topics)
        ncols = 2 if n > 6 else 1
        nrows = (n + ncols - 1) // ncols
        self.figure.set_size_inches(10, max(4, 1.8 * nrows))

        for i, topic in enumerate(topics, start=1):
            ax = self.figure.add_subplot(nrows, ncols, i)
            self._style_axes(ax)
            dset = self.datasets[topic]
            t = self._topic_time_seconds(dset)
            for f in sorted(dset.data.keys()):
                if f == "timestamp":
                    continue
                ax.plot(t, dset.data[f], linewidth=0.7)
            ax.set_title(topic, fontsize=8, color=COLORS["accent_2"], loc="left")
            ax.set_xlabel("t [s]", fontsize=7)

        self.figure.tight_layout()
        self.canvas.draw_idle()
        self._set_status(f"Plotted overview of {n} topics.")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette to override system widgets that don't use the stylesheet
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["bg_alt"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["bg_alt"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["bg_alt"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["bg"]))
    app.setPalette(palette)

    app.setStyleSheet(STYLESHEET)

    viewer = ULGViewer()
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
