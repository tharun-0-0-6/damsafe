import os
import sys
import subprocess
import time

PROJECT_DIR = r"F:\STUDY\Sem 6\CIP\Damsafe"
OUT_CSV = os.path.join(PROJECT_DIR, "outputs", "tables", "output_modules_1_2_3_4_7.csv")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_SCRIPT = os.path.join(SCRIPT_DIR, "modules_1_2_3_4_7.py")

QGIS_EXE_CANDIDATES = [
    r"F:\Applications\QGIS\bin\qgis-ltr-bin.exe",
]
QGIS_PROJECT_CANDIDATES = [
    os.path.join(PROJECT_DIR, "bhavani_sagar_dam.qgz"), 

]
REFRESH_INTERVAL_SEC = 2  # how often built-in window refreshes CSV
AUTO_REFRESH_SCRIPT = os.path.join(SCRIPT_DIR, "auto_refresh_qgis.py")

def find_qgis():
    exe = None
    for p in QGIS_EXE_CANDIDATES:
        if os.path.isfile(p):
            exe = p
            break
    proj = None
    for p in QGIS_PROJECT_CANDIDATES:
        if os.path.isfile(p):
            proj = p
            break
    return exe, proj


def start_pipeline():
    """Start pipeline subprocess with --app (launcher handles file delete)."""
    if os.path.exists(OUT_CSV):
        try:
            os.remove(OUT_CSV)
        except OSError:
            pass
    cmd = [sys.executable, PIPELINE_SCRIPT, "--app"]
    return subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def open_qgis(qgis_exe, project_path):
    """Open QGIS with project and auto-refresh script; wait for it to exit."""
    cmd = [qgis_exe, project_path]
    if os.path.isfile(AUTO_REFRESH_SCRIPT):
        cmd += ["--code", AUTO_REFRESH_SCRIPT]
        print(f"  Auto-refresh script: {AUTO_REFRESH_SCRIPT}")
    return subprocess.Popen(cmd, cwd=PROJECT_DIR)


def run_builtin_window():
    """Show a built-in map window: points colored by Dam_State_M4, recommendations on select."""
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter not available; cannot show built-in window.")
        return

    try:
        import pandas as pd
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import Patch
    except ImportError as e:
        print("matplotlib or pandas not available:", e)
        return

    COLS = {
        "state": "Dam_State_M4",
        "x_utm": "Blast_Easting",
        "y_utm": "Blast_Northing",
        "x_lon": "Blast_Lon",
        "y_lat": "Blast_Lat",
        "dist": "Distance_from_Dam_m",
        "rec_dist": "Rec_Distance_from_Dam_m",
        "rec_cf": "Rec_Charge_Factor",
        "rec_ppv": "Rec_Target_PPV_mm_per_s",
        "rec_burden": "Rec_Burden_m",
        "rec_spacing": "Rec_Spacing_m",
    }
    COLOR_MAP = {"Intact": "green", "Damaged": "yellow", "Failed": "red"}

    root = tk.Tk()
    root.wm_title("DamSafe — Live view")
    root.geometry("900x600")

    fig = Figure(figsize=(8, 5), dpi=100)
    ax = fig.add_subplot(111)
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    info_text = tk.Text(root, height=8, wrap=tk.WORD, font=("Consolas", 9))
    info_text.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)
    info_text.insert(tk.END, "Loading... (wait for CSV to be written). Click a point for details.\n")
    info_text.config(state=tk.DISABLED)

    current_df = [None]  # so pick handler can use the same df as the plot

    def read_csv_safe():
        if not os.path.exists(OUT_CSV):
            return None
        try:
            return pd.read_csv(OUT_CSV)
        except Exception:
            return None

    def get_xy(df):
        if df is None or df.empty:
            return None, None, False
        if "X" in df.columns and "Y" in df.columns:
            x = pd.to_numeric(df["X"], errors="coerce")
            y = pd.to_numeric(df["Y"], errors="coerce")
            if x.notna().any() and y.notna().any():
                return x, y, True
        if COLS["x_utm"] in df.columns and COLS["y_utm"] in df.columns:
            x = pd.to_numeric(df[COLS["x_utm"]], errors="coerce")
            y = pd.to_numeric(df[COLS["y_utm"]], errors="coerce")
            if x.notna().any() and y.notna().any():
                return x, y, True
        if COLS["x_lon"] in df.columns and COLS["y_lat"] in df.columns:
            x = pd.to_numeric(df[COLS["x_lon"]], errors="coerce")
            y = pd.to_numeric(df[COLS["y_lat"]], errors="coerce")
            if x.notna().any() and y.notna().any():
                return x, y, True
        x = df.index.astype(float)
        y = pd.to_numeric(df[COLS["dist"]], errors="coerce").fillna(0)
        return x, y, False

    def refresh_with_pick():
        df = read_csv_safe()
        ax.clear()
        if df is None or df.empty:
            ax.set_title("Waiting for data...")
            ax.set_xlabel("(CSV not yet created)")
            canvas.draw_idle()
            root.after(int(REFRESH_INTERVAL_SEC * 1000), refresh_with_pick)
            return
        x, y, is_map = get_xy(df)
        if x is None:
            root.after(int(REFRESH_INTERVAL_SEC * 1000), refresh_with_pick)
            return
        current_df[0] = df
        state_col = COLS["state"]
        if state_col in df.columns:
            colors = df[state_col].map(COLOR_MAP).fillna("gray")
            sc = ax.scatter(x, y, c=colors, s=30, alpha=0.8, edgecolors="black", linewidths=0.3, picker=5)
        else:
            sc = ax.scatter(x, y, c="gray", s=30, picker=5)
        ax.set_title("Intact (green) | Damaged (yellow) | Failed (red) — click point for details")
        if state_col in df.columns:
            legend_elements = [Patch(facecolor=c, label=s) for s, c in COLOR_MAP.items()]
            ax.legend(handles=legend_elements)
        if is_map:
            ax.set_xlabel("Easting / Longitude")
            ax.set_ylabel("Northing / Latitude")
            ax.set_aspect("equal", adjustable="datalim")
        else:
            ax.set_xlabel("Row index")
            ax.set_ylabel("Distance from dam (m)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        canvas.draw_idle()
        root.after(int(REFRESH_INTERVAL_SEC * 1000), refresh_with_pick)

    def on_pick(event):
        if not event.ind or current_df[0] is None:
            return
        df_cur = current_df[0]
        if len(df_cur) == 0:
            return
        idx = event.ind[0]
        if idx >= len(df_cur):
            return
        row = df_cur.iloc[idx]
        state_col = COLS["state"]
        state = row.get(state_col, "")
        lines = [
            f"Row {idx} | State: {state}",
            f"  Distance_from_Dam_m: {row.get(COLS['dist'], '')}",
        ]
        if state == "Failed":
            lines.append("  --- Recommendations ---")
            for k, col in [
                ("Rec Distance (m)", COLS["rec_dist"]),
                ("Rec Charge Factor", COLS["rec_cf"]),
                ("Rec PPV", COLS["rec_ppv"]),
                ("Rec Burden (m)", COLS["rec_burden"]),
                ("Rec Spacing (m)", COLS["rec_spacing"]),
            ]:
                if col in row.index and pd.notna(row.get(col)):
                    lines.append(f"  {k}: {row[col]}")
        info_text.config(state=tk.NORMAL)
        info_text.delete("1.0", tk.END)
        info_text.insert(tk.END, "\n".join(lines))
        info_text.config(state=tk.DISABLED)

    fig.canvas.mpl_connect("pick_event", on_pick)

    root.after(500, refresh_with_pick)

    def on_close():
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main():
    use_qgis = "--no-qgis" not in sys.argv

    if use_qgis:
        qgis_exe, project_path = find_qgis()
        if qgis_exe and project_path:
            # Pipeline is started by the toolbar button inside QGIS, not here.
            print("Opening QGIS with project:", project_path)
            print("  → Click '▶ Start DamSafe' inside QGIS to begin the pipeline.")
            qgis_proc = open_qgis(qgis_exe, project_path)
            qgis_proc.wait()
            print("QGIS closed.")
        else:
            print("QGIS or project not found; using built-in window.")
            if not qgis_exe:
                print("  QGIS exe not found at:", QGIS_EXE_CANDIDATES)
            if not project_path:
                print("  Project not found at:", QGIS_PROJECT_CANDIDATES)
            pipeline_proc = start_pipeline()
            run_builtin_window()
            pipeline_proc.terminate()
            try:
                pipeline_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pipeline_proc.kill()
    else:
        pipeline_proc = start_pipeline()
        run_builtin_window()
        pipeline_proc.terminate()
        try:
            pipeline_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pipeline_proc.kill()

    print("DamSafe app stopped.")


if __name__ == "__main__":
    main()
