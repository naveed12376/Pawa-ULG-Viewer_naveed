"""ULG (PX4 ULog) File Viewer
A Tkinter-based GUI for browsing and plotting all data inside a ULog file.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

try:
    from pyulog import ULog
except ImportError:
    print("Missing dependency: pyulog. Install it via:  pip install pyulog matplotlib")
    sys.exit(1)


class ULGViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ULG Data Viewer")
        self.geometry("1280x800")
        self.minsize(900, 600)

        self.ulog = None
        self.current_file = None
        self.datasets = {}          # name -> pyulog.ULog.Data
        self.field_map = {}         # tree item id -> (topic_name, field_name | None)

        self._build_style()
        self._build_ui()

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
        ttk.Button(top, text="Clear Plots", command=self.clear_plots).pack(side=tk.RIGHT)

        # Main paned window: left=tree, right=plots
        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Left side - topic/field tree
        left = ttk.Frame(main)
        main.add(left, weight=1)

        ttk.Label(left, text="Topics & Fields", style="Header.TLabel").pack(anchor="w", pady=(0, 4))

        search_frame = ttk.Frame(left)
        search_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_frame, text="Filter:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, selectmode="extended", show="tree")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", lambda e: self.plot_selected())

        # Right side - notebook with plots
        right = ttk.Frame(main)
        main.add(right, weight=4)

        ttk.Label(right, text="Plots", style="Header.TLabel").pack(anchor="w", pady=(0, 4))

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Status bar
        self.status = ttk.Label(self, text="Ready. Click 'Browse ULG File...' to begin.",
                                style="Status.TLabel", anchor="w", padding=(10, 4))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # --------------------------- File I/O --------------------------- #
    def browse_file(self):
        initial_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        if not os.path.isdir(initial_dir):
            initial_dir = os.path.dirname(os.path.abspath(__file__))

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
        self.clear_plots()
        n_topics = len(self.datasets)
        n_fields = sum(len(d.data) - 1 for d in self.datasets.values())  # minus timestamp
        self.status.config(
            text=f"Loaded {os.path.basename(path)}  |  {n_topics} topics, ~{n_fields} numeric fields. "
                 f"Select topics/fields and click Plot Selected, or use Plot All (Overview)."
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
    def clear_plots(self):
        for tab_id in self.notebook.tabs():
            self.notebook.forget(tab_id)

    def _add_plot_tab(self, fig, title):
        title = (title[:40] + "...") if len(title) > 43 else title
        tab = ttk.Frame(self.notebook)
        canvas = FigureCanvasTkAgg(fig, master=tab)
        canvas.draw()
        toolbar_frame = ttk.Frame(tab)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X)
        toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
        toolbar.update()
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.notebook.add(tab, text=title)
        self.notebook.select(tab)

    def _topic_time_seconds(self, dset):
        ts = dset.data.get("timestamp")
        if ts is None or len(ts) == 0:
            return None
        return (ts - ts[0]) / 1e6  # microseconds -> seconds

    def plot_selected(self):
        if not self.ulog:
            messagebox.showinfo("No file", "Load a ULG file first.")
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Nothing selected", "Select one or more topics or fields in the tree.")
            return

        # Group selected fields by topic
        by_topic = {}
        for item in selected:
            mapping = self.field_map.get(item)
            if not mapping:
                continue
            topic, field = mapping
            if field is None:
                # Topic-level selection: plot all of its fields
                dset = self.datasets[topic]
                for f in dset.data.keys():
                    if f != "timestamp":
                        by_topic.setdefault(topic, set()).add(f)
            else:
                by_topic.setdefault(topic, set()).add(field)

        if not by_topic:
            return

        for topic, fields in by_topic.items():
            dset = self.datasets[topic]
            t = self._topic_time_seconds(dset)
            if t is None:
                continue
            fields = sorted(fields)
            fig = Figure(figsize=(9, 5), dpi=100)
            ax = fig.add_subplot(111)
            for f in fields:
                y = dset.data.get(f)
                if y is None:
                    continue
                ax.plot(t, y, label=f, linewidth=0.9)
            ax.set_title(topic)
            ax.set_xlabel("time [s]")
            ax.set_ylabel("value")
            ax.grid(True, alpha=0.3)
            if len(fields) <= 12:
                ax.legend(loc="best", fontsize=8)
            fig.tight_layout()
            self._add_plot_tab(fig, topic)

        self.status.config(text=f"Plotted {len(by_topic)} topic(s).")

    def plot_all_overview(self):
        if not self.ulog:
            messagebox.showinfo("No file", "Load a ULG file first.")
            return

        if not messagebox.askyesno(
            "Plot all topics?",
            f"This will create one tab per topic ({len(self.datasets)} tabs).\n"
            "It may take a few seconds and use a lot of memory. Continue?",
        ):
            return

        self.status.config(text="Plotting all topics...")
        self.update_idletasks()

        plotted = 0
        for topic in sorted(self.datasets.keys()):
            dset = self.datasets[topic]
            t = self._topic_time_seconds(dset)
            if t is None:
                continue
            fields = [f for f in sorted(dset.data.keys()) if f != "timestamp"]
            if not fields:
                continue

            n = len(fields)
            ncols = 1 if n <= 4 else 2
            nrows = (n + ncols - 1) // ncols
            fig = Figure(figsize=(10, max(3, 1.6 * nrows)), dpi=100)
            for i, f in enumerate(fields, start=1):
                ax = fig.add_subplot(nrows, ncols, i)
                ax.plot(t, dset.data[f], linewidth=0.8)
                ax.set_title(f, fontsize=9)
                ax.grid(True, alpha=0.3)
                ax.tick_params(labelsize=7)
                if i > (nrows - 1) * ncols:
                    ax.set_xlabel("t [s]", fontsize=8)
            fig.suptitle(topic, fontsize=11, fontweight="bold")
            fig.tight_layout(rect=(0, 0, 1, 0.96))
            self._add_plot_tab(fig, topic)
            plotted += 1
            self.update_idletasks()

        self.status.config(text=f"Plotted overview of {plotted} topics.")


def main():
    app = ULGViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
