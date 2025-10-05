# SubplaceJoiner_Qt.py (patched v2)
# PySide6 UI + join flow fixes + persistence fixes

import time
import sys, os, json, uuid, threading, platform, webbrowser, subprocess, base64, re, stat
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

# --- ensure Requests ignores system proxies to avoid hangs ---

import requests
import asyncio
from PIL import Image, ImageDraw
try:
    from PIL.ImageQt import ImageQt
except Exception:
    ImageQt = None

# Optional deps used opportunistically
try:
    import psutil
except Exception:
    psutil = None

try:
    from mitmproxy import http  # type: ignore
    from mitmproxy.options import Options  # type: ignore
    from mitmproxy.tools.dump import DumpMaster  # type: ignore
    MITM_AVAILABLE = True
except Exception:
    MITM_AVAILABLE = False

try:
    import win32crypt  # type: ignore
except Exception:
    win32crypt = None

from PySide6.QtCore import Qt, QSize, QEvent, QTimer, QRectF, Signal, QObject
from PySide6.QtGui import QFont, QPalette, QColor, QFontMetrics, QPainter, QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea, QSplitter, QCheckBox,
    QFrame, QSizePolicy, QGraphicsDropShadowEffect, QMenu,
    QColorDialog, QSlider, QWidgetAction, QSplitterHandle
)

# ==================== Theming helpers ====================

def _safe_set_dpi_policy():
    try:
        policy_enum = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
        if policy_enum and hasattr(policy_enum, "PassThrough"):
            QApplication.setHighDpiScaleFactorRoundingPolicy(policy_enum.PassThrough)
    except Exception:
        pass

def make_shadow(blur=28, dx=0, dy=8, color=QColor(0,0,0,160)):
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur); eff.setOffset(dx, dy); eff.setColor(color)
    return eff

COLORS = {
    "bg_hi": "#151b25",
    "bg": "#12161B",
    "panel_top": "#161B24",
    "panel_bot": "#12161B",
    "border": "rgba(255,255,255,20)",
    "text": "#E5EAF1",
    "muted": "#8594AA",
    "title": "#BFD1FF",
    "chip_bg": "rgba(255,255,255,14)",
    "chip_border": "rgba(255,255,255,22)",
    "input_bg": "#0F131A",
    "accent": "#3B82F6",
    "ghost_bg": "rgba(255,255,255,18)",
    "ghost_border": "rgba(255,255,255,26)"
}

def gen_styles(text_color=None, btn_color=None):
    t = text_color or COLORS["text"]
    accent = btn_color or COLORS["accent"]
    return f"""
        QWidget {{ color: {t}; font-size: 13px; }}
        QLabel#Caption {{ color: {COLORS["muted"]}; }}
        QLabel#CardTitle {{ color: {COLORS["title"]}; letter-spacing: .3px; }}

        QFrame#HeroCard {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {COLORS["bg_hi"]}, stop:1 {COLORS["bg"]});
            border: 1px solid {COLORS["border"]};
            border-radius: 18px;
        }}
        QLabel#HeroSubtitle {{ color: #9bb0d1; }}

        QFrame#Card {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {COLORS["panel_top"]}, stop:1 {COLORS["panel_bot"]});
            border: 1px solid {COLORS["border"]};
            border-radius: 16px;
        }}

        QPushButton#AccentButton {{
            background: {accent}; color: #EAF2FF; border: none;
            border-radius: 12px; padding: 0 12px; font-weight: 600;
            min-height: 34px; max-height: 34px;
        }}

        QPushButton#GhostButton {{
            background: {COLORS["ghost_bg"]}; color: #CFD6E4;
            border: 1px solid {COLORS["ghost_border"]};
            border-radius: 17px; padding: 0 12px;
            min-height: 34px; max-height: 34px;
            font-weight: 600;
        }}

        QPushButton#Chip {{
            background: {COLORS["chip_bg"]};
            border: 1px solid {COLORS["chip_border"]};
            border-radius: 14px;
            padding: 0 12px;
            color: #D9E1F2;
            min-height: 28px; max-height: 28px;
        }}

        QCheckBox#PillCheck {{
            color: #CFD6E4 !important;
            background: {COLORS["ghost_bg"]};
            border: 1px solid {COLORS["ghost_border"]};
            border-radius: 17px;
            padding: 0 12px;
            min-height: 34px; max-height: 34px;
            font-weight: 600;
        }}
        QCheckBox#PillCheck::indicator {{
            width: 14px; height: 14px; border-radius: 7px;
            border: 1px solid {COLORS["ghost_border"]};
            background: {COLORS["ghost_bg"]};
            margin: 0 8px 0 0;
        }}
        QCheckBox#PillCheck::indicator:checked {{
            background: {accent}; border: 1px solid {accent};
        }}

        QLineEdit#Search {{
            border-radius: 12px;
            border: 1px solid {COLORS["ghost_border"]};
            background: {COLORS["input_bg"]};
            padding: 9px 12px;
            color: {t};
            selection-background-color: #2563EB;
            selection-color: white;
            min-height: 16px; max-height: 16px;
        }}

        QFrame#PlaceCard {{
            background: #141924;
            border: 1px solid rgba(255,255,255,18);
            border-radius: 14px;
        }}
        QLabel#Thumb {{
            background: rgba(255,255,255,14);
            border-radius: 12px;
        }}

        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical, QScrollBar:horizontal {{ width: 0px; height: 0px; }}
    """


def set_app_palette(app, theme):
    pal = app.palette()
    if theme == "light":
        pal.setColor(QPalette.Window, QColor(245,247,250))
        pal.setColor(QPalette.Base, QColor(255,255,255))
        pal.setColor(QPalette.Button, QColor(248,249,250))
        pal.setColor(QPalette.ButtonText, QColor(25,28,33))
        pal.setColor(QPalette.Text, QColor(25,28,33))
        pal.setColor(QPalette.WindowText, QColor(25,28,33))
    elif theme == "dark":
        pal.setColor(QPalette.Window, QColor(12,14,18))
        pal.setColor(QPalette.Base, QColor(18,21,27))
        pal.setColor(QPalette.Button, QColor(26,30,38))
        pal.setColor(QPalette.ButtonText, QColor(235,239,245))
        pal.setColor(QPalette.Text, QColor(235,239,245))
        pal.setColor(QPalette.WindowText, QColor(235,239,245))
    app.setPalette(pal)

# ---------------- custom splitter ----------------
HANDLE_HIT = 10
HANDLE_LINE = 2
HANDLE_GUTTER = (HANDLE_HIT - HANDLE_LINE) // 2

class ThinHandle(QSplitterHandle):
    def __init__(self, o, parent):
        super().__init__(o, parent)
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        x = (w - HANDLE_LINE) / 2.0
        r = QRectF(x, 0.0, HANDLE_LINE, self.height())
        color = QColor(255,255,255,30)
        p.setPen(Qt.NoPen); p.setBrush(color); p.drawRoundedRect(r, 1.6, 1.6)

class ThinSplitter(QSplitter):
    def __init__(self, orientation):
        super().__init__(orientation)
        self.setOpaqueResize(True)
    def createHandle(self):
        return ThinHandle(self.orientation(), self)

# ---------------- micro-widgets ----------------
class Card(QFrame):
    def __init__(self, title=None, object_name="Card", parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self._shadow = make_shadow(); self.setGraphicsEffect(self._shadow)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._l = QVBoxLayout(self)
        self._l.setContentsMargins(16,16,16,16); self._l.setSpacing(12)
        if title:
            t = QLabel(title); f=QFont(); f.setPointSize(11); f.setBold(True); t.setFont(f)
            t.setObjectName("CardTitle"); t.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._l.addWidget(t)
    def body(self): return self._l

class AccentButton(QPushButton):
    def __init__(self, text):
        super().__init__(text); self.setObjectName("AccentButton"); self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34); self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

class GhostButton(QPushButton):
    def __init__(self, text):
        super().__init__(text); self.setObjectName("GhostButton"); self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34); self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

class PillCheck(QCheckBox):
    def __init__(self, text):
        super().__init__(text); self.setObjectName("PillCheck"); self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMinimumHeight(34); self.setMaximumHeight(34)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

class Chip(QPushButton):
    def __init__(self, text, width=110, min_pt=9.0, base_pt=12.0):
        super().__init__(text); self.setObjectName("Chip"); self.setCursor(Qt.PointingHandCursor)
        self._chip_width = width; self._min_pt=min_pt; self._base_pt=base_pt
        self.setFixedWidth(self._chip_width); self.setMinimumHeight(28); self.setMaximumHeight(28)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self._fit_text()
    def _fit_text(self):
        padding = 24
        max_text = max(10, self._chip_width - padding)
        f = self.font(); f.setPointSizeF(self._base_pt)
        fm = QFontMetrics(f)
        while fm.horizontalAdvance(self.text()) > max_text and f.pointSizeF() > self._min_pt:
            f.setPointSizeF(f.pointSizeF() - 0.5); fm = QFontMetrics(f)
        self.setFont(f)
    def setChipWidth(self, w):
        self._chip_width = int(w); self.setFixedWidth(self._chip_width); self._fit_text()

class Search(QLineEdit):
    def __init__(self, ph):
        super().__init__(); self.setObjectName("Search"); self.setPlaceholderText(ph); self.setMinimumHeight(36)

class ChipFlow(QWidget):
    def __init__(self, labels, parent=None, chip_width=110, hspacing=8, vspacing=8,
                 margins=(10,8,10,10), min_width=90, max_width=240, target_width=110):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.grid = QGridLayout(self); self.grid.setContentsMargins(*margins)
        self.grid.setHorizontalSpacing(hspacing); self.grid.setVerticalSpacing(vspacing)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.min_width=int(min_width); self.max_width=int(max_width); self.target_width=int(target_width)
        self.chips = []
        self.set_labels(labels, chip_width)
        QTimer.singleShot(0, self.reflow)
    def set_labels(self, labels, chip_width=110):
        # clear
        for c in self.chips:
            c.setParent(None)
        self.chips = [Chip(str(s), width=chip_width) for s in labels]
        for c in self.chips:
            self.grid.addWidget(c, 0, 0)
        self.reflow()
    def setTargetWidth(self, w:int):
        self.target_width=max(48,int(w)); self.reflow()
    def setMinMaxWidth(self, min_w:int, max_w:int):
        self.min_width=int(min_w); self.max_width=int(max_w); self.reflow()
    def _inner_width(self):
        return max(1, self.contentsRect().width())
    def resizeEvent(self, e):
        super().resizeEvent(e); self.reflow()
    def reflow(self):
        if not self.chips: return
        l,t,r,b = self.grid.getContentsMargins()
        avail = max(1, self._inner_width() - l - r)
        spacing = self.grid.horizontalSpacing()
        tw = max(self.min_width, self.target_width)
        cols = max(1, (avail + spacing) // (tw + spacing))
        stretched = (avail - (cols - 1) * spacing) // cols
        chip_w = max(self.min_width, min(self.max_width, stretched))
        while self.grid.count():
            it = self.grid.takeAt(0); w = it.widget();
            if w is not None: w.setParent(self)
        for idx, w in enumerate(self.chips):
            w.setChipWidth(chip_w)
            self.grid.addWidget(w, idx // cols, idx % cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 0)

class FlowScroll(QScrollArea):
    def __init__(self, flow: ChipFlow):
        super().__init__(); self.setWidgetResizable(True); self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._flow = flow; self.setWidget(self._flow); self.viewport().installEventFilter(self)
    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Resize:
            self._flow.setMinimumWidth(self.viewport().width()); self._flow.setMaximumWidth(self.viewport().width()); self._flow.reflow()
        return super().eventFilter(obj, event)

# ---------------- PlaceCard with callbacks & async thumbnail ----------------





class PlaceCard(QFrame):
    def __init__(self, place, on_join, on_open, thumb_base=(200,120)):
        super().__init__(); self.setObjectName("PlaceCard")
        self._shadow = make_shadow(20,0,6,QColor(0,0,0,140)); self.setGraphicsEffect(self._shadow)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._thumb_base = thumb_base
        # normalize place dict and id keys (some APIs return 'id' or 'placeId')
        self.place = place or {}
        pid = self.place.get('id') or self.place.get('placeId') or self.place.get('place_id') or self.place.get('place')
        if pid is not None:
            try:
                pid = int(pid)
            except Exception:
                pass
        self.place['id'] = pid
        lay = QVBoxLayout(self); lay.setContentsMargins(12,12,12,12); lay.setSpacing(10)
        self.thumb = QLabel("(thumbnail)"); self.thumb.setObjectName("Thumb")
        self.thumb.setMinimumSize(*thumb_base); self.thumb.setAlignment(Qt.AlignCenter)
        title = f"{self.place.get('name','Unknown')} (ID: {self.place.get('id','?')})"
        if self.place.get('is_root'):
            title += "  ⭐ ROOT"
        self.title_lbl = QLabel(title); self.title_lbl.setWordWrap(True)
        f=QFont(); f.setPointSize(12); f.setBold(True); self.title_lbl.setFont(f)
        join_btn = AccentButton("Join"); open_btn = GhostButton("Open 🌐")
        join_btn.setFixedHeight(34); open_btn.setFixedHeight(34)
        join_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        open_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(); row.setSpacing(8); row.addWidget(join_btn); row.addWidget(open_btn)
        created_ago = self.time_ago(self.place.get('created'))
        updated_ago = self.time_ago(self.place.get('updated'))
        meta = QLabel(f"Created: {created_ago}\nUpdated: {updated_ago}")
        lay.addWidget(self.thumb); lay.addWidget(self.title_lbl); lay.addWidget(meta); lay.addLayout(row)
        self._update_fixed_height()
        # wiring
        join_btn.clicked.connect(lambda: on_join(self.place.get('id')))
        open_btn.clicked.connect(lambda: on_open(self.place.get('id')))
    def _update_fixed_height(self):
        self.adjustSize(); h = self.sizeHint().height(); self.setMaximumHeight(h)
    def set_thumb_scale(self, scale: float):
        w = max(140, int(self._thumb_base[0] * scale)); h = max(84, int(self._thumb_base[1] * scale))
        self.thumb.setMinimumSize(w, h); self.thumb.setMaximumHeight(h + 4); self._update_fixed_height()
    def time_ago(self, iso_time: str):
        """Convert ISO timestamp (e.g. '2025-09-30T12:35:16.34Z') into 'x days ago'."""
        if not iso_time:
            return "—"
        try:
            # Parse ISO 8601 (Roblox uses UTC Z suffix)
            dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            diff = now - dt
            seconds = diff.total_seconds()

            if seconds < 60:
                return f"{int(seconds)} seconds ago" if int(seconds) != 1 else "1 second ago"
            elif seconds < 3600:
                minutes = int(seconds / 60)
                return f"{minutes} minutes ago" if minutes != 1 else "1 minute ago"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{hours} hours ago" if hours != 1 else "1 hour ago"
            elif seconds < 2592000:
                days = int(seconds / 86400)
                return f"{days} days ago" if days != 1 else "1 day ago"
            elif seconds < 31536000:
                months = int(seconds / 2592000)
                return f"{months} months ago" if months != 1 else "1 month ago"
            else:
                years = int(seconds / 31536000)
                return f"{years} years ago" if years != 1 else "1 year ago"
        except Exception:
            return iso_time

# -------- collapsible hero --------
class CollapsibleHero(Card):
    def __init__(self, on_theme, on_text_color, on_btn_color, on_grid_size,
                 save_checkbox: QCheckBox, disable_join_checkbox: QCheckBox):
        super().__init__(None, object_name="HeroCard")
        self._chev = GhostButton("▾"); self._chev.setMinimumWidth(36)
        title = QLabel("Hopr GUI"); f=QFont(); f.setPointSize(12); f.setBold(True); title.setFont(f)
        subtitle = QLabel("Very fire UI🔥 • <-- Trust • Join sublaces! • 🤤😋"); subtitle.setObjectName("HeroSubtitle")
        header_row = QHBoxLayout(); header_row.addStretch(1)
        head_center = QVBoxLayout(); head_center.setSpacing(4)
        title.setAlignment(Qt.AlignCenter); subtitle.setAlignment(Qt.AlignCenter)
        head_center.addWidget(title); head_center.addWidget(subtitle)
        header_row.addLayout(head_center); header_row.addStretch(1); header_row.addWidget(self._chev)
        row = QHBoxLayout(); row.setSpacing(10); row.setAlignment(Qt.AlignHCenter)
        theme_btn = GhostButton("Theme"); theme_menu = QMenu(theme_btn)
        for name, key in [("System","system"),("Light","light"),("Dark","dark")]:
            act = theme_menu.addAction(name); act.triggered.connect(lambda _,k=key:on_theme(k))
        theme_btn.setMenu(theme_menu); theme_btn.clicked.connect(theme_btn.showMenu)
        text_btn = GhostButton("Text Color"); text_btn.clicked.connect(on_text_color)
        btncol_btn = GhostButton("Button Color"); btncol_btn.clicked.connect(on_btn_color)
        size_btn = GhostButton("Grid Size"); size_menu = QMenu(size_btn)
        size_container = QWidget(); size_layout = QHBoxLayout(size_container); size_layout.setContentsMargins(8,8,8,8)
        size_slider = QSlider(Qt.Horizontal); size_slider.setRange(200,420); size_slider.setValue(300); size_slider.setSingleStep(10)
        size_layout.addWidget(QLabel("Small")); size_layout.addWidget(size_slider); size_layout.addWidget(QLabel("Large"))
        wa = QWidgetAction(size_menu); wa.setDefaultWidget(size_container); size_menu.addAction(wa)
        size_btn.setMenu(size_menu); size_btn.clicked.connect(size_btn.showMenu); size_slider.valueChanged.connect(on_grid_size)
        save_checkbox.setParent(self); disable_join_checkbox.setParent(self)
        row.addWidget(theme_btn); row.addWidget(text_btn); row.addWidget(btncol_btn)
        row.addWidget(size_btn); row.addWidget(save_checkbox); row.addWidget(disable_join_checkbox)
        self.body().addLayout(header_row)
        self._settings_host = QWidget(); sh = QHBoxLayout(self._settings_host); sh.setContentsMargins(0,0,0,0); sh.addLayout(row)
        self.body().addWidget(self._settings_host)
        self._expanded = True; self._chev.clicked.connect(self._toggle)
    def _toggle(self):
        self._expanded = not self._expanded; self._settings_host.setVisible(self._expanded); self._chev.setText("▾" if self._expanded else "▸")

# ==================== Main Window ====================
from PySide6.QtCore import QObject, Signal, Qt, QTimer
class _MainThreadInvoker(QObject):
    call = Signal(object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.call.connect(self._run, Qt.QueuedConnection)
    def _run(self, fn):
        try:
            print('[DEBUG] _invoker: executing UI callback...')
            fn()
            print('[DEBUG] _invoker: UI callback complete')
        except Exception as e:
            import traceback
            print('[DEBUG] Exception in main-thread invoker:', e)
            traceback.print_exc()


class Window(QMainWindow):
    def _get(self, url, timeout=10):
        try:
            print(f"[HTTP GET] {url}")
            r = requests.get(url, timeout=timeout, proxies={})
            try:
                length = r.headers.get('Content-Length') or len(r.content or b'')
                snippet = (r.text[:300] + '...') if r.text and len(r.text) > 300 else r.text
                print(f"[HTTP GET DONE] {r.status_code} length={length}")
                ct = r.headers.get('Content-Type','')
                if 'application/json' in ct.lower() or 'text' in ct.lower():
                    print("[HTTP GET BODY SNIPPET]:", snippet)
            except Exception:
                pass
            return r
        except Exception as e:
            print(f"[HTTP GET ERROR] {url} -> {e}")
            raise
    def __init__(self):
        super().__init__()
        # Ensure queued UI callbacks run
        self._invoker = _MainThreadInvoker(self)

        self.setWindowTitle("Subplace Joiner — Qt")
        self.resize(1280, 820); self.setMinimumSize(780, 560)
        # state
        self._text_color=None; self._btn_color=None; self._card_width=300; self._theme="dark"
        self._cards=[]; self.root_place_id=None
        self.thumb_cache = {}  # place_id -> PIL Image

        # Use same settings path as Tk app for compatibility
        self.settings_path = Path.home() / "AppData/Local/SubplaceJoiner/settings.json"
        self.recent_ids = []
        self.favorites = set()
        self.cookie_visible = False
        self.disable_join_when_proxy = True
        self._proxy_thread = None
        self._proxy_ready = False
        self._search_inflight = False
        self._search_watchdog = None
        self._apply_theme(self._theme)
        self._build()
        self._apply_styles()
        self._load_settings()
        self._refresh_recents_and_favs()

    # ---------- Theme ----------
    def _apply_theme(self, theme):
        app = QApplication.instance(); app.setStyle("Fusion"); set_app_palette(app, theme)
    def _apply_styles(self):
        self.setStyleSheet(gen_styles(self._text_color, self._btn_color))

    # ---------- UI build ----------
    def _build(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central); outer.setContentsMargins(14,14,14,14); outer.setSpacing(12)
        # Settings checkboxes
        self.save_settings_chk = PillCheck("Save Settings"); self.save_settings_chk.setChecked(True)  # default ON
        self.disable_join_chk = PillCheck("Disable Join while Roblox/Proxy running"); self.disable_join_chk.setChecked(True)
        hero = CollapsibleHero(
            on_theme=self._on_theme,
            on_text_color=self._on_text_color,
            on_btn_color=self._on_btn_color,
            on_grid_size=self._on_grid_size_changed,
            save_checkbox=self.save_settings_chk,
            disable_join_checkbox=self.disable_join_chk
        ); outer.addWidget(hero)
        # search card
        search_card = Card()
        srow = QHBoxLayout(); srow.setSpacing(10)
        self.search = Search("Enter Place ID"); srow.addWidget(self.search, 2)
        self.search_btn = AccentButton("Search"); srow.addWidget(self.search_btn)
        self.fav_btn = GhostButton("★ Fav"); srow.addWidget(self.fav_btn)
        self.search_btn.clicked.connect(lambda _checked=False: self.on_search_clicked())
        self.search.returnPressed.connect(lambda: self.on_search_clicked())
        self.fav_btn.clicked.connect(self.on_toggle_favorite)
        search_card.body().addLayout(srow)
        cookie_row = QHBoxLayout(); cookie_row.setSpacing(10)
        self.cookie_edit = Search(".ROBLOSECURITY cookie (optional)"); self.cookie_edit.setEchoMode(QLineEdit.Password)
        cookie_row.addWidget(self.cookie_edit, 2)
        self.cookie_toggle = GhostButton("Show"); self.cookie_toggle.clicked.connect(self.on_toggle_cookie)
        cookie_row.addWidget(self.cookie_toggle)
        search_card.body().addLayout(cookie_row)
        self.error_lbl = QLabel(""); self.error_lbl.setObjectName("Caption"); search_card.body().addWidget(self.error_lbl)
        self.debug_lbl = QLabel(""); self.debug_lbl.setObjectName("Caption"); search_card.body().addWidget(self.debug_lbl)
        outer.addWidget(search_card)
        search_card._l.setContentsMargins(10, 8, 10, 8)
        search_card._l.setSpacing(67.67)
        search_card.setMinimumHeight(100)
        search_card.setMaximumHeight(100)
        # LEFT
        left_wrap = QWidget(); self.left_layout = QVBoxLayout(left_wrap); self.left_layout.setContentsMargins(0,0,HANDLE_GUTTER,0); self.left_layout.setSpacing(8)
        self.rec_card = Card("RECENT PLACE IDS"); self.fav_card = Card("FAVORITES")
        self._chip_target = int(self._card_width * 0.38)
        self.rec_flow = ChipFlow([], chip_width=110, target_width=self._chip_target)
        self.fav_flow = ChipFlow([], chip_width=110, target_width=self._chip_target)
        self.rec_scroll = FlowScroll(self.rec_flow); self.fav_scroll = FlowScroll(self.fav_flow)
        self.rec_card.body().addWidget(self.rec_scroll, 1); self.fav_card.body().addWidget(self.fav_scroll, 1)
        left_split = QSplitter(Qt.Vertical); left_split.setChildrenCollapsible(True); left_split.setHandleWidth(4)
        left_split.addWidget(self.rec_card); left_split.addWidget(self.fav_card); left_split.setSizes([240, 200])
        self.left_layout.addWidget(left_split)
        # RIGHT results grid
        self.right_wrap = QWidget(); self.right_layout = QVBoxLayout(self.right_wrap); self.right_layout.setContentsMargins(HANDLE_GUTTER,0,0,0); self.right_layout.setSpacing(0)
        right_card = Card("RESULTS"); right_card.setMinimumWidth(240)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget(); self.grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid = QGridLayout(self.grid_host); self.grid.setContentsMargins(8,8,8,8); self.grid.setHorizontalSpacing(12); self.grid.setVerticalSpacing(12); self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.grid_host); right_card.body().addWidget(self.scroll, 1)
        self.right_layout.addWidget(right_card)
        main_split = ThinSplitter(Qt.Horizontal); main_split.setChildrenCollapsible(True); main_split.setCollapsible(0, True); main_split.setHandleWidth(HANDLE_HIT)
        main_split.addWidget(left_wrap); main_split.addWidget(self.right_wrap); main_split.setSizes([320, 900])
        self.main_split = main_split; self.main_split.splitterMoved.connect(lambda *_: (self._snap_left_closed(), self._apply_collapse_margin()))
        outer.addWidget(self.main_split, 1)
        self.grid_host.installEventFilter(self)
        # footer
        foot = QHBoxLayout(); self.status = QLabel("Ready."); self.status.setObjectName("Caption"); foot.addWidget(self.status); foot.addStretch(1); outer.addLayout(foot)
        self._reflow_grid(); self._scale_thumbs(); QTimer.singleShot(0, self._apply_collapse_margin)

    # ---------- Event/layout helpers ----------
    def eventFilter(self, obj, event):
        if obj is self.grid_host and event.type() == QEvent.Resize:
            self._reflow_grid()
        return super().eventFilter(obj, event)
    def _reflow_grid(self):
        width = max(self.grid_host.width(), 1); cols = max(1, width // self._card_width)
        widgets=[]
        while self.grid.count():
            it = self.grid.takeAt(0); w = it.widget();
            if w: widgets.append(w)
        for i, w in enumerate(widgets):
            self.grid.addWidget(w, i // cols, i % cols)
    def _scale_thumbs(self):
        scale = max(0.55, min(1.45, (self._card_width / 300.0)))
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i); w = item.widget()
            if isinstance(w, PlaceCard):
                w.set_thumb_scale(scale)
                # Re-apply thumbnail at new size if it exists
                place_id = w.place.get('id')
                if place_id in self.thumb_cache:
                    pix = self._pil_to_qpix(self.thumb_cache[place_id])
                    if pix:
                        w.thumb.setPixmap(pix.scaled(w.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    def _apply_collapse_margin(self):
        sizes = self.main_split.sizes();
        if not sizes: return
        if sizes[0] == 0:
            shift = -(HANDLE_HIT + HANDLE_GUTTER - HANDLE_LINE)
            self.right_layout.setContentsMargins(shift,0,0,0)
        else:
            self.left_layout.setContentsMargins(0,0,HANDLE_GUTTER,0)
            self.right_layout.setContentsMargins(HANDLE_GUTTER,0,0,0)
    def _snap_left_closed(self):
        sizes = self.main_split.sizes();
        if not sizes: return
        threshold = max(6, self.main_split.handleWidth() + 4)
        if sizes[0] < threshold:
            total = sum(sizes); right = max(1, total - self.main_split.handleWidth())
            self.main_split.setSizes([0, right])

    # ---------- Settings callbacks ----------
    def _on_theme(self, key):
        self._theme = 'dark' if key in ('system','dark') else 'light'
        self._apply_theme(self._theme); self._apply_styles(); self._save_settings(force=True)
    def _on_text_color(self):
        c = QColorDialog.getColor(QColor(self._text_color or COLORS["text"]), self, "Choose text color")
        if c.isValid():
            self._text_color = c.name(); self._apply_styles(); self._save_settings(force=True)
    def _on_btn_color(self):
        c = QColorDialog.getColor(QColor(self._btn_color or COLORS["accent"]), self, "Choose button color")
        if c.isValid():
            self._btn_color = c.name(); self._apply_styles(); self._save_settings(force=True)
    def _on_grid_size_changed(self, val):
        self._card_width = int(val); self._reflow_grid(); self._scale_thumbs()
        tw = int(max(90, min(240, self._card_width * 0.38))); self._chip_target = tw
        self.rec_flow.setTargetWidth(tw); self.fav_flow.setTargetWidth(tw)

    # ---------- Search / Results ----------
    def on_search_clicked(self, *_):
        if self._search_inflight:
            print("[SEARCH] ignored: already running")
            return
        place_id = self.search.text().strip()
        if not place_id.isdigit():
            self._set_error("⚠️ Place ID must be a number"); return
        self._set_error(""); self.status.setText("Searching…"); self.search_btn.setEnabled(False); self.search_btn.setText("Searching…")
        self._search_inflight = True
        # history update (always persist)
        if place_id in self.recent_ids:
            self.recent_ids.remove(place_id)
        self.recent_ids.insert(0, place_id)
        self._save_settings(force=True); self._refresh_recents_and_favs()
        print(f"[SEARCH] start place={place_id}")
        # watchdog: auto-unstick UI after 15s
        try:
            if self._search_watchdog is not None:
                self._search_watchdog.stop()
        except Exception:
            pass
        self._search_watchdog = QTimer(self); self._search_watchdog.setSingleShot(True)
        self._search_watchdog.timeout.connect(self._search_timeout)
        self._search_watchdog.start(15000)
        threading.Thread(target=self._search_worker, args=(place_id,), daemon=True).start()

    def _search_worker(self, place_id: str):
        print("[SEARCH] worker begin")
        try:
            # Step 1: Get universe ID from place
            u = self._get(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe", timeout=10)
            u.raise_for_status()
            universe_data = u.json()
            universe_id = universe_data.get("universeId")
            if not universe_id:
                raise Exception("Invalid Place ID or universe not found")

            # Step 1.5: Get the actual root place ID from universe details
            universe_details = self._get(f"https://games.roblox.com/v1/games?universeIds={universe_id}", timeout=10)
            universe_details.raise_for_status()
            games_data = universe_details.json().get("data", [])
            if games_data:
                self.root_place_id = games_data[0].get("rootPlaceId")
            else:
                # Fallback: assume searched place is root if we can't get universe details
                self.root_place_id = int(place_id)

            cursor = None
            all_places = []
            seen = set()

            # Step 2: Paginate through all places and display immediately
            while True:
                url = f"https://develop.roblox.com/v1/universes/{universe_id}/places?limit=100"
                if cursor:
                    url += f"&cursor={cursor}"
                r = self._get(url, timeout=10)
                r.raise_for_status()
                data = r.json()
                batch = data.get("data", [])

                if not batch:
                    print("[DEBUG] Empty batch received, stopping.")
                    break

                # Process batch and add to all_places immediately
                for p in batch:
                    pid = p.get("id")
                    if pid in seen:
                        continue
                    seen.add(pid)
                    
                    # Set default values for timestamps
                    p["created"] = None
                    p["updated"] = None
                    
                    # Mark root place - now using the actual root place ID
                    if self.root_place_id and int(pid) == int(self.root_place_id):
                        p["is_root"] = True
                    
                    all_places.append(p)

                # Check next cursor
                next_cursor = data.get("nextPageCursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor

            print("[DEBUG] Got all places, displaying immediately:", len(all_places))
            print(f"[DEBUG] Root place ID detected as: {self.root_place_id}")
            
            # Display results immediately without timestamps
            self._on_main(lambda: (self._debug_api_detected(len(all_places)), self.display_results(all_places.copy())))

            # Now load timestamps asynchronously in background
            cookie = self.cookie_edit.text().strip() or self.get_roblosecurity() or ""
            
            def load_timestamps():
                updated_places = []
                for i, p in enumerate(all_places):
                    pid = p.get("id")
                    
                    while True:
                        try:
                            asset_url = f"https://economy.roblox.com/v2/assets/{pid}/details"
                            response = requests.get(asset_url, cookies={".ROBLOSECURITY": cookie}, timeout=10)
                            response.raise_for_status()
                            asset_data = response.json()

                            p["created"] = asset_data.get("Created")
                            p["updated"] = asset_data.get("Updated")
                            
                            print(f"[DEBUG] Place {pid}: created={p['created']}, updated={p['updated']}")
                            break

                        except requests.HTTPError as err:
                            status = getattr(err.response, "status_code", None)
                            if status in (429, 500, 502, 503, 504):
                                print(f"[WARN] Rate-limited or server error on {pid} (HTTP {status}); retrying in 1 s…")
                                time.sleep(1)
                                continue
                            else:
                                print(f"[WARN] HTTP error on {pid}: {err}")
                                break

                        except Exception as perr:
                            print(f"[WARN] Could not fetch asset details for {pid}: {perr}")
                            break
                    
                    updated_places.append(p)
                    
                    # Update UI periodically (every 5 places) to show progress
                    if (i + 1) % 5 == 0 or i == len(all_places) - 1:
                        places_copy = updated_places.copy()
                        self._on_main(lambda pc=places_copy: self._update_existing_cards_with_timestamps(pc))

            # Start timestamp loading in separate thread
            threading.Thread(target=load_timestamps, daemon=True).start()

        except Exception as e:
            self._on_main(lambda err=e: self._set_error(f"⚠️ {err}"))

        finally:
            self._on_main(lambda: self._search_done_ui_reset())

    def _update_existing_cards_with_timestamps(self, updated_places):
        """Update existing PlaceCard widgets with new timestamp data"""
        try:
            # Create a mapping of place_id -> updated place data
            place_map = {p.get('id'): p for p in updated_places}
            
            # Update existing cards
            for i in range(self.grid.count()):
                item = self.grid.itemAt(i)
                if item and item.widget():
                    card = item.widget()
                    if isinstance(card, PlaceCard):
                        card_id = card.place.get('id')
                        if card_id in place_map:
                            # Update the place data
                            updated_place = place_map[card_id]
                            card.place.update(updated_place)
                            
                            # Update the meta label with new timestamps
                            created_ago = card.time_ago(updated_place.get('created'))
                            updated_ago = card.time_ago(updated_place.get('updated'))
                            
                            # Find the meta label and update it
                            for child in card.findChildren(QLabel):
                                if child.text().startswith("Created:"):
                                    child.setText(f"Created: {created_ago}\nUpdated: {updated_ago}")
                                    break
                                    
        except Exception as e:
            print(f"[DEBUG] Error updating timestamps: {e}")

    def display_results(self, places):
        while self.grid.count():
            it = self.grid.takeAt(0); w = it.widget();
            if w: w.setParent(None)
        if not places:
            self.status.setText("No places found."); return
        if isinstance(places, dict):
            places = [places]
        cols = max(1, max(1, self.grid_host.width() // self._card_width))
        for i, p in enumerate(places):
            if isinstance(p, dict):
                pid = p.get('id') or p.get('placeId')
                if pid is not None:
                    try: p['id'] = int(pid)
                    except Exception: p['id'] = pid
            card = PlaceCard(p, on_join=self.join_flow, on_open=self.open_in_browser)
            self.grid.addWidget(card, i // cols, i % cols)
            # Start thumbnail loading immediately for each card
            self._load_thumb_async_immediate(p.get('id'), card)
        self._reflow_grid(); self._scale_thumbs(); self.status.setText(f"Found {len(places)} places")

    def _load_thumb_async_immediate(self, place_id, card: PlaceCard):
        """Load thumbnail immediately without waiting"""
        def worker():
            try:
                pix = self._fetch_thumb_pixmap(place_id)
                self._on_main(lambda: self._apply_thumb(card, pix))
            except Exception as e:
                print(f"[THUMB] Error loading thumbnail for {place_id}: {e}")
                self._on_main(lambda: card.thumb.setText("(no image)"))
        threading.Thread(target=worker, daemon=True).start()

    def _search_done_ui_reset(self):
        try:
            if self._search_watchdog is not None:
                self._search_watchdog.stop()
        except Exception:
            pass
        self._search_inflight = False
        try:
            self.search_btn.setEnabled(True)
            self.search_btn.setText("Search")
            if not self.status.text() or self.status.text().strip().lower()=="searching…":
                self.status.setText("Ready.")
        except Exception:
            pass
        print("[SEARCH] worker end")

    def _search_timeout(self):
        print("[SEARCH] watchdog fired — resetting UI")
        self._search_inflight = False
        try:
            self.search_btn.setEnabled(True)
            self.search_btn.setText("Search")
            if not self.status.text() or self.status.text().strip().lower()=="searching…":
                self.status.setText("Timed out. Try again.")
        except Exception:
            pass

    def _debug_api_detected(self, count):
        try:
            msg = f"[DEBUG] API responded with {count} places"
            print(msg)
            self.debug_lbl.setText(msg)
        except Exception as e:
            print("[DEBUG] failed to update debug label", e)

    # ---------- Thumbs ----------
    def _load_thumb_async(self, place_id, card: PlaceCard):
        def worker():
            pix = self._fetch_thumb_pixmap(place_id)
            self._on_main(lambda: self._apply_thumb(card, pix))
        threading.Thread(target=worker, daemon=True).start()
    def _apply_thumb(self, card: PlaceCard, pix: QPixmap|None):
        if pix is None:
            card.thumb.setText("(no image)"); return
        card.thumb.setPixmap(pix.scaled(card.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    def _fetch_thumb_pixmap(self, place_id) -> QPixmap|None:
        if place_id in self.thumb_cache:
            return self._pil_to_qpix(self.thumb_cache[place_id])
        try:
            meta = self._get(f"https://thumbnails.roblox.com/v1/places/gameicons?placeIds={place_id}&size=512x512&format=Png", timeout=10)
            meta.raise_for_status(); data = meta.json(); img_url = data.get("data", [{}])[0].get("imageUrl")
            if not img_url: return None
            img_response = self._get(img_url, timeout=10); img_response.raise_for_status()
            pil = Image.open(BytesIO(img_response.content)).convert("RGBA")
            size = min(pil.width, pil.height)
            img = pil.resize((size, size))
            mask = Image.new("L", (size, size), 0); draw = ImageDraw.Draw(mask); draw.rounded_rectangle((0,0,size,size), radius=size//6, fill=255)
            img.putalpha(mask)
            self.thumb_cache[place_id] = img
            return self._pil_to_qpix(img)
        except Exception:
            return None
    def _pil_to_qpix(self, pil_img) -> QPixmap|None:
        if pil_img is None: return None
        if ImageQt is None:
            b = BytesIO(); pil_img.save(b, format='PNG'); b.seek(0)
            qimg = QImage.fromData(b.read(), 'PNG'); return QPixmap.fromImage(qimg)
        qimg = ImageQt(pil_img)
        if isinstance(qimg, QImage):
            return QPixmap.fromImage(qimg)
        return QPixmap.fromImage(QImage(qimg))

    # ---------- Favorites / Recents ----------
    def on_toggle_favorite(self):
        pid = self.search.text().strip()
        if not pid.isdigit():
            return
        if pid in self.favorites:
            self.favorites.remove(pid); self.status.setText(f"Removed {pid} from favorites"); self.fav_btn.setText("★ Fav")
        else:
            self.favorites.add(pid); self.status.setText(f"Added {pid} to favorites"); self.fav_btn.setText("★ Faved")
        self._save_settings(force=True); self._refresh_recents_and_favs()
    def _refresh_recents_and_favs(self):
        self.rec_flow.set_labels(self.recent_ids[:200])
        self.fav_flow.set_labels(sorted(self.favorites, key=lambda x:int(x)) if self.favorites else [])
        for chip in self.rec_flow.chips:
            chip.clicked.connect(lambda _, t=chip.text(): self._quick_search(t))
        for chip in self.fav_flow.chips:
            chip.clicked.connect(lambda _, t=chip.text(): self._quick_search(t))
        cur = self.search.text().strip()
        if cur and cur in self.favorites:
            self.fav_btn.setText("★ Faved")
        else:
            self.fav_btn.setText("★ Fav")

    def _quick_search(self, place_id: str):
        self.search.setText(str(place_id)); self.on_search_clicked()

    # ---------- Cookie visibility ----------
    def on_toggle_cookie(self):
        self.cookie_visible = not self.cookie_visible
        self.cookie_edit.setEchoMode(QLineEdit.Normal if self.cookie_visible else QLineEdit.Password)
        self.cookie_toggle.setText("Hide" if self.cookie_visible else "Show")

    # ---------- Join flow ----------
    def join_flow(self, place_id):
        
        # Record subplace in recents immediately
        pid = str(place_id)
        if pid.isdigit():
            if pid in self.recent_ids:
                self.recent_ids.remove(pid)
            self.recent_ids.insert(0, pid)
            self._save_settings(force=True); self._refresh_recents_and_favs()

        cookie = (self.cookie_edit.text().strip() or self.get_roblosecurity() or "")
        try:
            # Pre-seed join for ROOT explicitly (backend expects root first)
            root = int(self.root_place_id or place_id)
            if cookie:
                ok = self._preseed_join_root(root, cookie)
                if not ok:
                    self._set_error("⚠️ GameJoin seed failed; launching anyway…")
            self.status.setText("Launching Roblox…")
            print("[DEEPLINK FIRING]", f"roblox://experiences/start?placeId={place_id}", "root", self.root_place_id)
            self.launch_roblox(place_id)
            self.start_proxy_thread()
        except Exception as e:
            self._set_error(f"⚠️ {e}"); self.status.setText("Failed to launch Roblox")

    def _new_session(self, cookie: str|None):
        sess = requests.Session()
        # IMPORTANT: avoid inheriting system proxies; don't let mitm catch this pre-seed
        sess.trust_env = False
        sess.proxies = {}
        sess.headers.update({
            "User-Agent": "Roblox/WinInet",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
        })
        if cookie:
            sess.headers["Cookie"] = f".ROBLOSECURITY={cookie};"
        # X-CSRF
        try:
            r = sess.post("https://auth.roblox.com/v2/logout", timeout=10)
            token = r.headers.get("x-csrf-token") or r.headers.get("X-CSRF-TOKEN")
            if token:
                sess.headers["X-CSRF-TOKEN"] = token
        except Exception:
            pass
        return sess

    def _preseed_join_root(self, root_place_id: int, cookie: str):
        try:
            sess = self._new_session(cookie)
            payload = {
                "placeId": int(root_place_id),
                "isTeleport": True,
                "isImmersiveAdsTeleport": False,
                "gameJoinAttemptId": str(uuid.uuid4()),
            }
            print("[JOIN PRESEED FIRING]", json.dumps(payload, indent=2))
            r = sess.post("https://gamejoin.roblox.com/v1/join-game", json=payload, timeout=15)
            print("[JOIN PRESEED STATUS]", r.status_code)
            try: print("[JOIN PRESEED BODY]", r.text[:800])
            except Exception: pass
            data = {}
            try: data = r.json()
            except Exception: pass
            # Status 2 == ready to join
            return (r.status_code == 200 and data.get("status") == 2)
        except Exception as e:
            print("[JOIN PRESEED ERROR]", e)
            return False

    def start_proxy_thread(self):
        if not MITM_AVAILABLE or psutil is None:
            self.status.setText("Proxy not available. (Install mitmproxy + psutil for full flow)")
            return
        if getattr(self, "_proxy_thread", None) and self._proxy_thread.is_alive():
            return
        def runner():
            asyncio.run(self._proxy_main())
        self._proxy_thread = threading.Thread(target=runner, daemon=True)
        self._proxy_thread.start()
        self.status.setText("Proxy running…")
        if self.disable_join_chk.isChecked():
            self._enable_disable_join_buttons(False)

    async def _proxy_main(self):
        PROXY_HOST = "127.0.0.1"; PROXY_PORT = 51823
        proxy_settings = {
            "DFStringHttpCurlProxyHostAndPort": f"{PROXY_HOST}:{PROXY_PORT}",
            "DFStringDebugPlayerHttpProxyUrl": f"http://{PROXY_HOST}:{PROXY_PORT}",
            "DFFlagDebugEnableHttpProxy": "True",
            "DFStringHttpCurlProxyHostAndPortForExternalUrl": f"{PROXY_HOST}:{PROXY_PORT}",
        }
        class Interceptor:
            WANTED = (
                "/v1/join-game",
                "/v1/join-game-instance",
                "/v1/join-play-together-game",
                "/v1/join-play-together-game-instance",
            )
            def request(self, flow: 'http.HTTPFlow') -> None:
                url = flow.request.pretty_url
                if any(p in url for p in self.WANTED):
                    content_type = flow.request.headers.get("Content-Type", "")
                    if "application/json" in content_type.lower():
                        try:
                            body_json = flow.request.json()
                        except Exception:
                            return
                        if "isTeleport" not in body_json:
                            body_json["isTeleport"] = True
                            print("added teleport")
                        body_json.setdefault("gameJoinAttemptId", str(uuid.uuid4()))
                        flow.request.set_text(json.dumps(body_json))
            def response(self, flow: 'http.HTTPFlow') -> None:
                pass
        options = Options(listen_host=PROXY_HOST, listen_port=PROXY_PORT)
        master = DumpMaster(options, with_termlog=False, with_dumper=False)
        master.addons.add(Interceptor())
        asyncio.create_task(master.run())
        # Wait for Roblox start & restore settings similar to original
        ca_path = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"
        for _ in range(200):
            if ca_path.exists():
                break
            await asyncio.sleep(0.05)
        apps = {
            "Roblox": Path.home() / "AppData/Local/Roblox",
            "Bloxstrap": Path.home() / "AppData/Local/Bloxstrap",
            "Fishstrap": Path.home() / "AppData/Local/Fishstrap",
        }
        original_settings = {}
        for app_name, path in apps.items():
            versions_path = path / "Versions"
            if not versions_path.exists():
                continue
            for version_folder in versions_path.iterdir():
                if not version_folder.is_dir():
                    continue
                exe_files = list(version_folder.glob("*PlayerBeta.exe"))
                if not exe_files:
                    continue
                # Ensure libcurl bundle includes mitm CA
                ssl_folder = version_folder / "ssl"; ssl_folder.mkdir(exist_ok=True)
                ca_file = ssl_folder / "cacert.pem"
                try:
                    if ca_path.exists():
                        mitm_ca_content = ca_path.read_text(encoding="utf-8")
                        if ca_file.exists():
                            existing_content = ca_file.read_text(encoding="utf-8")
                            if mitm_ca_content not in existing_content:
                                with open(ca_file, "a", encoding="utf-8") as f:
                                    f.write("\n" + mitm_ca_content)
                        else:
                            with open(ca_file, "w", encoding="utf-8") as f:
                                f.write(mitm_ca_content)
                except Exception:
                    pass
        # ClientSettings override
        roblox_path = Path.home() / "AppData" / "Local" / "Roblox"

        if not roblox_path.exists():
            messagebox.showwarning("Roblox not found", "Please install Roblox")

        # File path
        file_path = roblox_path / "ClientSettings" / "IxpSettings.json"

        if not file_path.exists():
            print("File does not exist, creating it.")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.touch()
        try:
            existing = {}
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            original_settings[str(file_path)] = existing
            updated = dict(existing); updated.update(proxy_settings)
            
            os.chmod(file_path, stat.S_IWRITE)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(updated, f, indent=4)
            os.chmod(file_path, stat.S_IREAD)
        except Exception:
            pass
        self._on_main(lambda: self.status.setText("Waiting for Roblox to start…"))
        count=0
        while True:
            if psutil and any((p.info.get('name') or '').lower()=="robloxplayerbeta.exe" for p in psutil.process_iter(['name'])):
                break
            else:
                count += 1
                if count >= 100:
                    for file_path, content in original_settings.items():
                        try:
                            os.chmod(file_path, stat.S_IWRITE)
                            with open(file_path, "w", encoding="utf-8") as f:
                                json.dump(content, f, indent=4)
                            os.chmod(file_path, stat.S_IREAD)
                        except Exception:
                            pass
                    try:
                        await master.shutdown()
                    except Exception:
                        pass
                    self._on_main(lambda: (self._enable_disable_join_buttons(True), self.status.setText("Proxy stopped. Roblox did not open.")))
                    return
            await asyncio.sleep(0.1)

        count = 0
        while True:
            if any((p.info.get('name') or '').lower() == "robloxcrashhandler.exe" for p in psutil.process_iter(['name'])):
                break
            if not any((p.info.get('name') or '').lower() == "robloxplayerbeta.exe" for p in psutil.process_iter(['name'])):
                count += 1
                if count >= 50:
                    for file_path, content in original_settings.items():
                        try:
                            os.chmod(file_path, stat.S_IWRITE)
                            with open(file_path, "w", encoding="utf-8") as f:
                                json.dump(content, f, indent=4)
                            os.chmod(file_path, stat.S_IREAD)
                        except Exception as e:
                            print(f"[proxy] restore failed {file_path}: {e}")
                    try:
                        await master.shutdown()
                    except Exception:
                        pass
                    self._on_main(lambda: (self._enable_disable_join_buttons(True), self.status.setText("Proxy stopped. Roblox closed unexpectedly.")))
                    return
            else:
                count = 0
            await asyncio.sleep(0.1)

        # After start, restore original files
        for file_path, content in original_settings.items():
            try:
                os.chmod(file_path, stat.S_IWRITE)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, indent=4)
                os.chmod(file_path, stat.S_IREAD)
            except Exception:
                pass
        # Wait for exit, then shutdown
        while True:
            if psutil and not any((p.info.get('name') or '').lower()=="robloxplayerbeta.exe" for p in psutil.process_iter(['name'])):
                try:
                    await master.shutdown()
                except Exception:
                    pass
                self._on_main(lambda: (self._enable_disable_join_buttons(True), self.status.setText("Proxy stopped. Ready.")))
                break
            await asyncio.sleep(0.5)

    def _enable_disable_join_buttons(self, enable: bool):
        for i in range(self.grid.count()):
            w = self.grid.itemAt(i).widget()
            if isinstance(w, PlaceCard):
                for child in w.findChildren(QPushButton):
                    if child.text().startswith("Join"):
                        child.setEnabled(enable)

    # ---------- Launch & helpers ----------
    def launch_roblox(self, place_id):
        roblox_url = f"roblox://experiences/start?placeId={place_id}"
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(roblox_url)
            elif system == "Darwin":
                subprocess.run(["open", roblox_url], check=False)
            else:
                subprocess.run(["xdg-open", roblox_url], check=False)
        except Exception:
            webbrowser.open(roblox_url)

    def open_in_browser(self, place_id):
        try:
            # Also record to recents when opening in browser
            pid = str(place_id)
            if pid.isdigit():
                if pid in self.recent_ids:
                    self.recent_ids.remove(pid)
                self.recent_ids.insert(0, pid)
                self._save_settings(force=True); self._refresh_recents_and_favs()
            webbrowser.open(f"https://www.roblox.com/games/{place_id}")
        except Exception:
            pass

    # ---------- Cookie auto-read (Windows DPAPI) ----------
    def get_roblosecurity(self):
        path = os.path.expandvars(r"%LocalAppData%/Roblox/LocalStorage/RobloxCookies.dat")
        try:
            if not os.path.exists(path):
                return None
            with open(path, "r") as f:
                data = json.load(f)
            cookies_data = data.get("CookiesData")
            if not cookies_data or not win32crypt:
                return None
            enc = base64.b64decode(cookies_data)
            dec = win32crypt.CryptUnprotectData(enc, None, None, None, 0)[1]
            s = dec.decode(errors="ignore")
            m = re.search(r"\.ROBLOSECURITY\s+([^\s;]+)", s)
            return m.group(1) if m else None
        except Exception:
            return None

    # ---------- Settings persistence ----------
    def _load_settings(self):
        try:
            d = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        self.recent_ids = list(d.get("recent_ids", []))
        self.favorites = set(x for x in d.get("favorites", []) if str(x).isdigit())
        self._theme = d.get("theme", self._theme)
        self._text_color = d.get("text_color", self._text_color)
        self._btn_color = d.get("btn_color", self._btn_color)
        if d.get("save_settings", True):
            self.save_settings_chk.setChecked(True)
        self._apply_theme(self._theme); self._apply_styles()
    def _save_settings(self, force=False):
        # Persist history/favorites regardless; theme/colors guarded by checkbox unless force=True
        d = {
            "recent_ids": self.recent_ids[:200],
            "favorites": sorted(self.favorites, key=lambda x:int(x)),
        }
        if self.save_settings_chk.isChecked() or force:
            d.update({
                "theme": self._theme,
                "text_color": self._text_color,
                "btn_color": self._btn_color,
                "save_settings": self.save_settings_chk.isChecked(),
            })
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(d, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------- Misc ----------
    def _set_error(self, text):
        self.error_lbl.setText(text)
    def _on_main(self, fn):
        inv = getattr(self, '_invoker', None)
        if inv is not None:
            print('[DEBUG] _on_main: queuing UI work via signal')
            inv.call.emit(fn)
            return
        print('[DEBUG] _on_main: fallback QTimer.singleShot')
        try:
            QTimer.singleShot(0, fn)
        except Exception as e:
            import traceback
            print('[DEBUG] _on_main fallback failed:', e)
            traceback.print_exc()

if __name__ == "__main__":
    _safe_set_dpi_policy()
    app = QApplication(sys.argv)
    w = Window(); w.show()
    sys.exit(app.exec())