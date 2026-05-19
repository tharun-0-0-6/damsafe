"""
DamSafe QGIS Auto-Refresh Script  (v4 — toolbar-button start/stop)
-------------------------------------------------------------------
Adds a "▶ Start DamSafe" / "■ Stop DamSafe" toolbar to QGIS.
Nothing runs until you click Start.

Usage (inside QGIS):
  1. Ctrl+Alt+P  →  Python Console
  2. Show Editor (notepad icon) → Open this file → Run (green ▶)
  3. Click "▶ Start DamSafe" on the toolbar that appears.
"""

import os, sys, csv, subprocess, traceback, time
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsField, QgsMarkerSymbol,
    QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
    QgsRuleBasedLabeling,
)
from qgis.utils import iface
from PyQt5.QtCore import QTimer, QVariant
from PyQt5.QtWidgets import QApplication, QToolBar, QMessageBox
from PyQt5.QtGui import QColor, QFont, QIcon

# ── CONFIG ──────────────────────────────────────────────────────────
PROJECT_DIR = r"F:\STUDY\Sem 6\CIP\Damsafe"
CSV_PATH = os.path.join(PROJECT_DIR, "outputs", "tables", "output_modules_1_2_3_4_7.csv")
PIPELINE_SCRIPT = os.path.join(PROJECT_DIR, "scripts", "modules_1_2_3_4_7.py")
REFRESH_MS = 1000
LAYER_NAME = "DamSafe_Live_Auto"
X_CANDIDATES = ["X", "Blast_lon", "Blast_Lon", "Longitude"]
Y_CANDIDATES = ["Y", "Blast_lat", "Blast_Lat", "Latitude"]
STATE_COL = "Dam_State_M4"
POINT_DISPLAY_SECONDS = 10  # how long each point stays visible on the map
TOOLBAR_NAME = "DamSafe"
# ────────────────────────────────────────────────────────────────────

_last_row_count = -1
_recent_points = []    # list of (timestamp, row_dict) for buffered points
_last_csv_content = None  # to detect when the CSV row changes
_pipeline_proc = None  # subprocess handle for the streaming pipeline
_refresh_timer = None  # QTimer for auto-refresh


def _find_xy_cols(headers):
    x_col = y_col = None
    for c in X_CANDIDATES:
        if c in headers:
            x_col = c
            break
    for c in Y_CANDIDATES:
        if c in headers:
            y_col = c
            break
    return x_col, y_col


def _apply_dam_state_style(layer):
    """Color points by Dam_State_M4: green/yellow/red."""
    categories = []
    for state, color in [("Intact", "#00cc00"), ("Damaged", "#ffcc00"), ("Failed", "#ff0000")]:
        sym = QgsMarkerSymbol.createSimple({
            "name": "circle", "size": "3.5",
            "color": color, "outline_color": "#333333", "outline_width": "0.3",
        })
        cat = QgsRendererCategory(state, sym, state)
        categories.append(cat)
    renderer = QgsCategorizedSymbolRenderer(STATE_COL, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def _apply_recommendation_labels(layer):
    """Show recommendation labels for Failed points, adapting detail to zoom level.
    - Zoomed out (scale > 50,000): top 2 fields (Distance, PPV)
    - Medium zoom (10,000–50,000): top 3 fields (+Charge)
    - Zoomed in  (scale < 10,000): all 5 fields
    """
    # All recommendation fields in priority order
    rec_fields = [
        ("Rec Distance", "Rec_Distance_from_Dam_m"),
        ("Rec PPV", "Rec_Target_PPV_mm_per_s"),
        ("Rec Charge", "Rec_Charge_Factor"),
        ("Rec Burden", "Rec_Burden_m"),
        ("Rec Spacing", "Rec_Spacing_m"),
    ]

    def _build_expr(fields_to_show):
        """Build a label expression for a subset of recommendation fields."""
        parts = []
        for label, col in fields_to_show:
            parts.append(
                f'if("{col}" IS NOT NULL AND "{col}" != \'\' AND "{col}" != \'nan\', '
                f"'{label}: ' || \"{col}\" || '\\n', '')"
            )
        return " || ".join(parts)

    def _make_label_settings(expression):
        """Create QgsPalLayerSettings with the given expression."""
        settings = QgsPalLayerSettings()
        settings.fieldName = expression
        settings.isExpression = True
        settings.enabled = True

        text_format = QgsTextFormat()
        font = QFont("Arial", 7)
        font.setBold(True)
        text_format.setFont(font)
        text_format.setSize(7)
        text_format.setColor(QColor(255, 0, 0))       # ← TEXT COLOR (red)

        buf = QgsTextBufferSettings()
        buf.setEnabled(False)                          # ← SHADOW/BUFFER off
        text_format.setBuffer(buf)

        settings.setFormat(text_format)
        return settings

    # Build expressions for each zoom tier
    expr_2 = _build_expr(rec_fields[:2])   # Distance + PPV
    expr_3 = _build_expr(rec_fields[:3])   # + Charge
    expr_5 = _build_expr(rec_fields)       # all 5

    failed_filter = '"Dam_State_M4" = \'Failed\''

    root_rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())

    # Rule 1: zoomed out (scale > 50,000) → 2 fields
    rule_far = QgsRuleBasedLabeling.Rule(_make_label_settings(expr_2))
    rule_far.setFilterExpression(failed_filter)
    rule_far.setDescription("Recs (zoomed out)")
    rule_far.setActive(True)
    rule_far.setMaximumScale(50001)   # applies when scale > 50,000
    root_rule.appendChild(rule_far)

    # Rule 2: medium zoom (10,000–50,000) → 3 fields
    rule_mid = QgsRuleBasedLabeling.Rule(_make_label_settings(expr_3))
    rule_mid.setFilterExpression(failed_filter)
    rule_mid.setDescription("Recs (medium zoom)")
    rule_mid.setActive(True)
    rule_mid.setMinimumScale(50000)
    rule_mid.setMaximumScale(10001)
    root_rule.appendChild(rule_mid)

    # Rule 3: zoomed in (scale < 10,000) → all 5 fields
    rule_close = QgsRuleBasedLabeling.Rule(_make_label_settings(expr_5))
    rule_close.setFilterExpression(failed_filter)
    rule_close.setDescription("Recs (zoomed in)")
    rule_close.setActive(True)
    rule_close.setMinimumScale(10000)
    root_rule.appendChild(rule_close)

    labeling = QgsRuleBasedLabeling(root_rule)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)


def _read_csv(path):
    """Read CSV manually (no pandas dependency inside QGIS)."""
    rows = []
    headers = []
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                rows.append(row)
    except Exception:
        pass
    return headers, rows


def _get_or_create_layer(headers):
    """Find existing memory layer or create a new one."""
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.name() == LAYER_NAME:
            return lyr, False

    mem = QgsVectorLayer("Point?crs=EPSG:4326", LAYER_NAME, "memory")
    pr = mem.dataProvider()
    fields = []
    for h in headers:
        fields.append(QgsField(h, QVariant.String))
    pr.addAttributes(fields)
    mem.updateFields()

    QgsProject.instance().addMapLayer(mem)
    _apply_dam_state_style(mem)
    _apply_recommendation_labels(mem)
    return mem, True


def auto_refresh():
    """Read CSV → buffer new points → display all points within the 5-second window."""
    global _last_row_count, _recent_points, _last_csv_content

    try:
        if not os.path.isfile(CSV_PATH):
            return

        headers, rows = _read_csv(CSV_PATH)
        if not headers or not rows:
            return

        now = time.time()

        # Check if the CSV content changed (new point arrived at the end)
        csv_key = str(rows[-1])  # monitor the LATEST row, not the first
        if csv_key != _last_csv_content:
            _last_csv_content = csv_key
            _recent_points.append((now, rows[-1]))

        # Expire points older than POINT_DISPLAY_SECONDS (5s)
        _recent_points = [
            (t, r) for t, r in _recent_points
            if (now - t) < POINT_DISPLAY_SECONDS
        ]

        _last_row_count = len(_recent_points)

        x_col, y_col = _find_xy_cols(headers)
        if not x_col or not y_col:
            print(f"Cannot find X/Y columns in: {headers}")
            return

        layer, is_new = _get_or_create_layer(headers)
        pr = layer.dataProvider()

        # ── Save current map view so it doesn't jump ──
        canvas = iface.mapCanvas()
        saved_extent = canvas.extent()

        # ── Clear old features ──
        layer.startEditing()
        fids = [f.id() for f in layer.getFeatures()]
        if fids:
            layer.deleteFeatures(fids)
        layer.commitChanges()

        # ── Add all buffered points ──
        features = []
        field_names = [fld.name() for fld in pr.fields()]
        for _, row in _recent_points:
            try:
                xv = float(row.get(x_col, ""))
                yv = float(row.get(y_col, ""))
            except (ValueError, TypeError):
                continue
            feat = QgsFeature(pr.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(xv, yv)))
            attrs = []
            for fn in field_names:
                attrs.append(str(row.get(fn, "")))
            feat.setAttributes(attrs)
            features.append(feat)

        if features:
            pr.addFeatures(features)
            layer.updateExtents()

        layer.triggerRepaint()

        # ── Restore the map view so the base map stays visible ──
        canvas.setExtent(saved_extent)
        canvas.refresh()
        QApplication.processEvents()

        print(f"🔄 Showing {len(features)} points ({len(_recent_points)} buffered)")

    except Exception as e:
        print(f"❌ auto_refresh error: {e}")
        traceback.print_exc()


def _remove_damsafe_layers():
    """Remove ALL vector layers from the project (memory layers, CSV layers, etc.).
    Only raster layers (base satellite map) are kept."""
    project = QgsProject.instance()
    ids_to_remove = []
    for lyr in project.mapLayers().values():
        if isinstance(lyr, QgsVectorLayer):
            ids_to_remove.append((lyr.id(), lyr.name()))
    for lid, lname in ids_to_remove:
        project.removeMapLayer(lid)
        print(f"   Removed layer: {lname}")


# =====================================================================
#  TOOLBAR  —  ▶ Start DamSafe  /  ■ Stop DamSafe
# =====================================================================

def _start_damsafe():
    """Called when the user clicks '▶ Start DamSafe'."""
    global _pipeline_proc, _refresh_timer, _last_row_count

    # Prevent double-start
    if _refresh_timer is not None and _refresh_timer.isActive():
        print("⚠ DamSafe is already running.  Click Stop first.")
        return

    # Reset state
    _last_row_count = -1
    _recent_points = []
    _last_csv_content = None

    # Clean up any leftover layers from a previous run
    _remove_damsafe_layers()

    # Delete old output so pipeline starts fresh
    if os.path.exists(CSV_PATH):
        try:
            os.remove(CSV_PATH)
        except OSError:
            pass

    # Launch the streaming pipeline as a background subprocess
    ext_python = os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(ext_python):
        ext_python = "python"
    _pipeline_proc = subprocess.Popen(
        [ext_python, PIPELINE_SCRIPT, "--app"],
        cwd=os.path.dirname(PIPELINE_SCRIPT),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    print(f"🚀 Pipeline started (PID {_pipeline_proc.pid})")

    # Start the auto-refresh timer
    _refresh_timer = QTimer()
    _refresh_timer.timeout.connect(auto_refresh)
    _refresh_timer.start(REFRESH_MS)

    print(f"✅ DamSafe RUNNING — refresh every {REFRESH_MS} ms")
    print(f"   CSV: {CSV_PATH}")

    # Update button states
    _start_action.setEnabled(False)
    _stop_action.setEnabled(True)


def _stop_damsafe():
    """Called when the user clicks '■ Stop DamSafe'."""
    global _pipeline_proc, _refresh_timer

    # Stop the refresh timer
    if _refresh_timer is not None:
        _refresh_timer.stop()
        _refresh_timer.deleteLater()
        _refresh_timer = None

    # Kill the pipeline subprocess
    if _pipeline_proc is not None:
        try:
            _pipeline_proc.terminate()
            _pipeline_proc.wait(timeout=5)
        except Exception:
            try:
                _pipeline_proc.kill()
            except Exception:
                pass
        _pipeline_proc = None

    # Keep layers and CSV intact so points + recommendations stay visible
    print("🛑 DamSafe stopped. Points and recommendations remain on the map.")

    # Update button states
    _start_action.setEnabled(True)
    _stop_action.setEnabled(False)


# ── Remove any previous DamSafe toolbar (re-run safe) ──
_main_window = iface.mainWindow()
for tb in _main_window.findChildren(QToolBar):
    if tb.objectName() == TOOLBAR_NAME:
        _main_window.removeToolBar(tb)
        tb.deleteLater()

# ── Clean up any leftover layers from a previous session ──
_remove_damsafe_layers()

# ── Delete any leftover output CSV so stale data can't show ──
if os.path.exists(CSV_PATH):
    try:
        os.remove(CSV_PATH)
        print("   Deleted leftover output CSV.")
    except OSError:
        pass

# ── Create the toolbar ──
_toolbar = QToolBar(TOOLBAR_NAME, _main_window)
_toolbar.setObjectName(TOOLBAR_NAME)
_main_window.addToolBar(_toolbar)

_start_action = _toolbar.addAction("▶ Start DamSafe")
_stop_action  = _toolbar.addAction("■ Stop DamSafe")
_stop_action.setEnabled(False)  # disabled until pipeline is running

_start_action.triggered.connect(_start_damsafe)
_stop_action.triggered.connect(_stop_damsafe)

print("🔧 DamSafe toolbar added — click '▶ Start DamSafe' to begin.")