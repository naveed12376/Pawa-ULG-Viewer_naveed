"""ULG (PX4 ULog) File Viewer
A Tkinter-based GUI for browsing and plotting all data inside a ULog file.
Favorites are persisted to settings.txt in the workspace.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

try:
    from pyulog import ULog
except ImportError:
    print("Missing dependency: pyulog. Install it via:  pip install pyulog matplotlib")
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.txt")


class ULGViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ULG Data Viewer")
        self.geometry("1280x800")
        self.minsize(900, 600)

        self.ulog = None
        self.current_file = None
        self.datasets = {}                # name -> pyulog.ULog.Data
        self.field_map = {}               # tree item id -> (topic_name, field_name | None)
        self.fav_map = {}                 # fav tree item id -> (topic_name, field_name)
        self.favorites = self._load_favorites()  # list of (topic, field) preserving order

        self._build_style()
        self._build_ui()
        self._refresh_favorites_tree()

    # ----------------------------- UI ----------------------------- #
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=6)
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", foreground="#555")

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(top, text="Browse ULG File...", command=self.browse_file).pack(side=tk.LEFT)
        self.file_label = ttk.Label(top, text="No file loaded", style="Status.TLabel")
        self.file_label.pack(side=tk.LEFT, padx=12)

        ttk.Button(top, text="Plot Selected", command=self.plot_selected).pack(side=tk.RIGHT)
        ttk.Button(top, text="Plot All (Overview)", command=self.plot_all_overview).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Clear Plot", command=self.clear_plot).pack(side=tk.RIGHT)

        # Main paned window: left=trees, right=plot
        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Left side - vertical paned: Favorites on top, Topics below
        left = ttk.Panedwindow(main, orient=tk.VERTICAL)
        main.add(left, weight=1)

        # ---- Favorites pane ----
        fav_frame = ttk.Frame(left)
        left.add(fav_frame, weight=1)

        fav_header = ttk.Frame(fav_frame)
        fav_header.pack(fill=tk.X)
        ttk.Label(fav_header, text="Favorites", style="Header.TLabel").pack(side=tk.LEFT, pady=(0, 4))
        ttk.Button(fav_header, text="Remove", command=self.remove_selected_favorite, width=8)\
            .pack(side=tk.RIGHT)

        fav_tree_frame = ttk.Frame(fav_frame)
        fav_tree_frame.pack(fill=tk.BOTH, expand=True)
        self.fav_tree = ttk.Treeview(fav_tree_frame, selectmode="extended", show="tree")
        fav_vsb = ttk.Scrollbar(fav_tree_frame, orient="vertical", command=self.fav_tree.yview)
        self.fav_tree.configure(yscrollcommand=fav_vsb.set)
        self.fav_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fav_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.fav_tree.bind("<Double-1>", lambda e: self.plot_selected())
        self.fav_tree.bind("<Delete>", lambda e: self.remove_selected_favorite())

        self.fav_menu = tk.Menu(self, tearoff=0)
        self.fav_menu.add_command(label="Remove from Favorites", command=self.remove_selected_favorite)
        self.fav_menu.add_command(label="Plot", command=self.plot_selected)
        self.fav_tree.bind("<Button-3>", self._on_fav_right_click)

        # ---- Topics pane ----
        topics_frame = ttk.Frame(left)
        left.add(topics_frame, weight=3)

        ttk.Label(topics_frame, text="Topics & Fields", style="Header.TLabel").pack(anchor="w", pady=(0, 4))

        search_frame = ttk.Frame(topics_frame)
        search_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_frame, text="Filter:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tree_frame = ttk.Frame(topics_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, selectmode="extended", show="tree")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", lambda e: self.plot_selected())

        self.tree_menu = tk.Menu(self, tearoff=0)
        self.tree_menu.add_command(label="Add to Favorites", command=self.add_selected_to_favorites)
        self.tree_menu.add_command(label="Plot", command=self.plot_selected)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # ---- Right side - single persistent plot ----
        right = ttk.Frame(main)
        main.add(right, weight=4)

        ttk.Label(right, text="Plot", style="Header.TLabel").pack(anchor="w", pady=(0, 4))

        self.figure = Figure(figsize=(9, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        toolbar_frame = ttk.Frame(right)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._draw_empty_message("Load a ULG file and select fields to plot.")

        # Status bar
        self.status = ttk.Label(self, text="Ready. Click 'Browse ULG File...' to begin.",
                                style="Status.TLabel", anchor="w", padding=(10, 4))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------ Right-click context menus ------------------ #
    def _on_tree_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
        try:
            self.tree_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tree_menu.grab_release()

    def _on_fav_right_click(self, event):
        row = self.fav_tree.identify_row(event.y)
        if row:
            if row not in self.fav_tree.selection():
                self.fav_tree.selection_set(row)
        try:
            self.fav_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.fav_menu.grab_release()

    # ------------------------ Favorites I/O ------------------------ #
    def _load_favorites(self):
        favs = []
        if not os.path.isfile(SETTINGS_FILE):
            return favs
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "|" not in line:
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
            messagebox.showerror("Save failed", f"Could not write {SETTINGS_FILE}:\n{e}")

    def add_selected_to_favorites(self):
        selected = self.tree.selection()
        if not selected:
            return
        added = 0
        for item in selected:
            mapping = self.field_map.get(item)
            if not mapping:
                continue
            topic, field = mapping
            if field is None:
                # Topic-level: add every field of this topic
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
            self.status.config(text=f"Added {added} favorite(s).")
        else:
            self.status.config(text="Selected item(s) already in favorites.")

    def remove_selected_favorite(self):
        selected = self.fav_tree.selection()
        if not selected:
            return
        to_remove = []
        for item in selected:
            entry = self.fav_map.get(item)
            if entry:
                to_remove.append(entry)
        if not to_remove:
            return
        self.favorites = [fv for fv in self.favorites if fv not in to_remove]
        self._save_favorites()
        self._refresh_favorites_tree()
        self.status.config(text=f"Removed {len(to_remove)} favorite(s).")

    def _refresh_favorites_tree(self):
        self.fav_tree.delete(*self.fav_tree.get_children())
        self.fav_map.clear()
        for topic, field in self.favorites:
            # Mark fields that aren't present in the currently loaded file
            missing = bool(self.ulog) and (
                topic not in self.datasets or field not in self.datasets[topic].data
            )
            label = f"{topic} / {field}" + ("   [not in file]" if missing else "")
            iid = self.fav_tree.insert("", "end", text=label)
            self.fav_map[iid] = (topic, field)

    # --------------------------- File I/O --------------------------- #
    def browse_file(self):
        initial_dir = os.path.join(SCRIPT_DIR, "data")
        if not os.path.isdir(initial_dir):
            initial_dir = SCRIPT_DIR

        path = filedialog.askopenfilename(
            title="Select a ULG File",
            initialdir=initial_dir,
            filetypes=[("ULog files", "*.ulg"), ("All files", "*.*")],
        )
        if not path:
            return
        self.load_file(path)

    def load_file(self, path):
        self.status.config(text=f"Loading {os.path.basename(path)}...")
        self.update_idletasks()
        try:
            ulog = ULog(path)
        except Exception as e:
            messagebox.showerror("Failed to load ULG", f"Could not load file:\n{e}")
            self.status.config(text="Load failed.")
            return

        self.ulog = ulog
        self.current_file = path
        self.datasets = {d.name + (f"_{d.multi_id}" if d.multi_id else ""): d for d in ulog.data_list}
        self.file_label.config(text=os.path.basename(path))
        self._populate_tree()
        self._refresh_favorites_tree()
        self.clear_plot()
        n_topics = len(self.datasets)
        n_fields = sum(len(d.data) - 1 for d in self.datasets.values())
        self.status.config(
            text=f"Loaded {os.path.basename(path)}  |  {n_topics} topics, ~{n_fields} numeric fields."
        )

    # ------------------------ Tree population ------------------------ #
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.field_map.clear()

        for topic_name in sorted(self.datasets.keys()):
            dset = self.datasets[topic_name]
            n_samples = len(next(iter(dset.data.values()))) if dset.data else 0
            topic_id = self.tree.insert("", "end", text=f"{topic_name}  ({n_samples} samples)", open=False)
            self.field_map[topic_id] = (topic_name, None)
            for field in sorted(dset.data.keys()):
                if field == "timestamp":
                    continue
                fid = self.tree.insert(topic_id, "end", text=field)
                self.field_map[fid] = (topic_name, field)

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        if not query:
            self._populate_tree()
            return
        self.tree.delete(*self.tree.get_children())
        self.field_map.clear()

        for topic_name in sorted(self.datasets.keys()):
            dset = self.datasets[topic_name]
            matching_fields = [f for f in sorted(dset.data.keys())
                               if f != "timestamp" and (query in f.lower() or query in topic_name.lower())]
            topic_match = query in topic_name.lower()
            if not matching_fields and not topic_match:
                continue
            n_samples = len(next(iter(dset.data.values()))) if dset.data else 0
            topic_id = self.tree.insert("", "end", text=f"{topic_name}  ({n_samples} samples)", open=True)
            self.field_map[topic_id] = (topic_name, None)
            fields_to_show = matching_fields if not topic_match else [
                f for f in sorted(dset.data.keys()) if f != "timestamp"
            ]
            for field in fields_to_show:
                fid = self.tree.insert(topic_id, "end", text=field)
                self.field_map[fid] = (topic_name, field)

    # --------------------------- Plotting --------------------------- #
    def _topic_time_seconds(self, dset):
        ts = dset.data.get("timestamp")
        if ts is None or len(ts) == 0:
            return None
        return (ts - ts[0]) / 1e6  # microseconds -> seconds

    def _draw_empty_message(self, msg):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color="#777")
        ax.set_axis_off()
        self.canvas.draw_idle()

    def clear_plot(self):
        self._draw_empty_message("Plot cleared. Select fields and click Plot Selected.")
        self.status.config(text="Plot cleared.")

    def _collect_selection(self):
        """Build {topic: set(fields)} from both Favorites and Topics tree selections."""
        by_topic = {}

        for item in self.fav_tree.selection():
            entry = self.fav_map.get(item)
            if not entry:
                continue
            topic, field = entry
            if topic in self.datasets and field in self.datasets[topic].data:
                by_topic.setdefault(topic, set()).add(field)

        for item in self.tree.selection():
            mapping = self.field_map.get(item)
            if not mapping:
                continue
            topic, field = mapping
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

    def plot_selected(self):
        if not self.ulog:
            messagebox.showinfo("No file", "Load a ULG file first.")
            return

        by_topic = self._collect_selection()
        if not by_topic:
            messagebox.showinfo("Nothing selected",
                                "Select one or more entries in Favorites or Topics & Fields.")
            return

        self.figure.clear()
        n_topics = len(by_topic)
        topics_sorted = sorted(by_topic.keys())

        for idx, topic in enumerate(topics_sorted, start=1):
            ax = self.figure.add_subplot(n_topics, 1, idx)
            dset = self.datasets[topic]
            t = self._topic_time_seconds(dset)
            if t is None:
                continue
            fields = sorted(by_topic[topic])
            for f in fields:
                y = dset.data.get(f)
                if y is None:
                    continue
                ax.plot(t, y, label=f, linewidth=0.9)
            ax.set_title(topic, fontsize=10)
            ax.set_ylabel("value", fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=8)
            if len(fields) <= 12:
                ax.legend(loc="best", fontsize=7)
            if idx == n_topics:
                ax.set_xlabel("time [s]")

        self.figure.tight_layout()
        self.canvas.draw_idle()
        self.status.config(text=f"Plotted {n_topics} topic(s).")

    def plot_all_overview(self):
        if not self.ulog:
            messagebox.showinfo("No file", "Load a ULG file first.")
            return

        topics = [t for t in sorted(self.datasets.keys())
                  if self._topic_time_seconds(self.datasets[t]) is not None
                  and any(f != "timestamp" for f in self.datasets[t].data.keys())]
        if not topics:
            return

        if not messagebox.askyesno(
            "Plot all topics?",
            f"This will draw one subplot per topic ({len(topics)} subplots) on a single figure.\n"
            "It may be cramped and slow to render. Continue?",
        ):
            return

        self.status.config(text="Plotting all topics...")
        self.update_idletasks()

        self.figure.clear()
        n = len(topics)
        ncols = 2 if n > 6 else 1
        nrows = (n + ncols - 1) // ncols
        self.figure.set_size_inches(10, max(4, 1.8 * nrows))

        for i, topic in enumerate(topics, start=1):
            ax = self.figure.add_subplot(nrows, ncols, i)
            dset = self.datasets[topic]
            t = self._topic_time_seconds(dset)
            fields = [f for f in sorted(dset.data.keys()) if f != "timestamp"]
            for f in fields:
                ax.plot(t, dset.data[f], linewidth=0.7, label=f)
            ax.set_title(topic, fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=6)
            ax.set_xlabel("t [s]", fontsize=7)

        self.figure.tight_layout()
        self.canvas.draw_idle()
        self.status.config(text=f"Plotted overview of {n} topics.")


def main():
    app = ULGViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
