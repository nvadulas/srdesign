import tkinter as tk
from tkinter import filedialog
import os
import threading
import time

try:
    from pygame import mixer
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ── Sensor imports (graceful fallback for dev without hardware) ──────────────
try:
    import board
    import busio
    import digitalio
    import adafruit_vl53l1x
    SENSORS_AVAILABLE = True
except (ImportError, NotImplementedError):
    SENSORS_AVAILABLE = False

# ── Color palette ────────────────────────────────────────────────────────────
BG        = "#0D0D0F"
SURFACE   = "#161619"
BORDER    = "#2A2A30"
ACCENT    = "#6F2DA8"
ACCENT2   = "#E6E6FA"
TEXT_PRI  = "#F0EDE8"
TEXT_SEC  = "#7A7880"
BTN_PLAY  = "#6F2DA8"
BTN_HOVER = "#9B59D0"
SLIDER_TR = "#2A2A30"
PDF_BG    = "#12121A"
PDF_SURF  = "#1A1A24"
PDF_ACC   = "#9B6FD4"

# Active panel highlight
PANEL_ACTIVE_BORDER = "#6F2DA8"
PANEL_INACTIVE_BORDER = "#2A2A30"

# Sensor indicator colors
SENSOR_OFF        = "#1A1A20"
SENSOR_ON         = "#6F2DA8"
SENSOR_SWIPE      = "#9B59D0"
SENSOR_HOLD       = "#C084FC"
SENSOR_BORDER_OFF = "#2A2A35"
SENSOR_BORDER_ON  = "#9B59D0"

PLAYER_W  = 380
PDF_W     = 520
WIN_H     = 880

# ── Hardcoded PDF list ────────────────────────────────────────────────────────
PDF_LIST = [
    ("Datasheet",  "/home/agadkari/srdesign/PDFs/datasheet.pdf"),
    ("Homework",   "/home/agadkari/srdesign/PDFs/hw.pdf"),
    ("NPB", "/home/agadkari/srdesign/PDFs/npb.pdf"),
    ("Resume", "/home/agadkari/srdesign/PDFs/resume.pdf"),
]

# ── Hardcoded playlist ────────────────────────────────────────────────────────
PLAYLIST = [
    ("Dance",  "/home/agadkari/srdesign/Music/dance.mp3"),
    ("Stomp",  "/home/agadkari/srdesign/Music/stomp.mp3"),
    ("Phonk",  "/home/agadkari/srdesign/Music/phonk.mp3"),
    ("Joyful", "/home/agadkari/srdesign/Music/joyful.mp3"),
    ("Action", "/home/agadkari/srdesign/Music/action.mp3"),
]

# ── Sensor / gesture constants ────────────────────────────────────────────────
XSHUT_LEFT_PIN  = None
XSHUT_RIGHT_PIN = None
PRESENT_MM    = 300
DOMINANCE_MM  = 40
SWIPE_TIMEOUT = 0.5
HOLD_TIME     = 3.0
NO_READING    = 65535

# Double-swipe detection: two swipes within this window = panel switch
DOUBLE_SWIPE_WINDOW = 0.8   # seconds

# Volume gesture constants
VOLUME_STEP             = 5    # percent per gesture tick
VOLUME_HOLD_REPEAT_SEC  = 0.6  # seconds between repeated volume steps while held

if SENSORS_AVAILABLE:
    XSHUT_LEFT_PIN  = board.D17
    XSHUT_RIGHT_PIN = board.D27

# ─────────────────────────────────────────────────────────────────────────────
#  Sensor helpers
# ─────────────────────────────────────────────────────────────────────────────
def make_xshut(pin):
    x = digitalio.DigitalInOut(pin)
    x.direction = digitalio.Direction.OUTPUT
    return x

def init_sensors():
    xshut_left  = make_xshut(XSHUT_LEFT_PIN)
    xshut_right = make_xshut(XSHUT_RIGHT_PIN)
    xshut_left.value  = False
    xshut_right.value = False
    time.sleep(0.5)
    xshut_left.value = True
    time.sleep(0.5)
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50
    sensor_left.set_address(0x30)
    time.sleep(0.5)
    i2c.deinit()
    time.sleep(0.5)
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c, address=0x30)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50
    xshut_right.value = True
    time.sleep(0.5)
    sensor_right = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_right.distance_mode = 1
    sensor_right.timing_budget = 50
    return sensor_left, sensor_right

def read_one(sensor):
    try:
        sensor.start_ranging()
        timeout = time.monotonic() + 0.5
        while not sensor.data_ready:
            if time.monotonic() > timeout:
                sensor.stop_ranging()
                return NO_READING
            time.sleep(0.005)
        dist = sensor.distance
        sensor.clear_interrupt()
        sensor.stop_ranging()
        return round(dist * 10) if dist is not None else NO_READING
    except OSError:
        return NO_READING

# ─────────────────────────────────────────────────────────────────────────────
#  Main Application
# ─────────────────────────────────────────────────────────────────────────────
class MusicPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Delta Music Player")
        self.root.geometry(f"{PLAYER_W + PDF_W}x{WIN_H}")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        if PYGAME_AVAILABLE:
            mixer.init()

        self.current_file   = None
        self.paused         = False
        self._drag_start    = None

        # PDF state
        self.pdf_doc        = None
        self.pdf_path       = None
        self.current_page   = 0
        self.total_pages    = 0
        self.zoom_level     = 1.0
        self._pdf_img_ref   = None

        # Pre-populate from hardcoded PDF_LIST (relative paths resolved to script dir)
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        self._recent_pdfs = [
            (name, p if os.path.isabs(p) else os.path.join(_script_dir, p))
            for name, p in PDF_LIST
        ]

        # Volume state (0–100)
        self._volume        = 50

        # ── Active panel: "music" or "pdf"
        # Gestures adapt based on which panel is focused
        self._active_panel  = "music"

        # Double-swipe tracking
        self._last_swipe_time = 0.0
        self._last_swipe_dir  = None   # "LR" or "RL"

        # Gesture state
        self._gesture_running = True

        self._build_ui()
        self._remove_title_bar()
        self._update_panel_indicators()

        if SENSORS_AVAILABLE:
            t = threading.Thread(target=self._sensor_loop, daemon=True)
            t.start()
        else:
            t = threading.Thread(target=self._demo_sensor_loop, daemon=True)
            t.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self._gesture_running = False
        self.root.destroy()

    # ── Window drag ──────────────────────────────────────────────────────────
    def _remove_title_bar(self):
        self.root.overrideredirect(True)
        self.drag_bar.bind("<ButtonPress-1>",  self._start_drag)
        self.drag_bar.bind("<B1-Motion>",       self._do_drag)
        self.drag_bar.bind("<ButtonRelease-1>", self._stop_drag)

    def _start_drag(self, e):
        self._drag_start = (e.x_root - self.root.winfo_x(),
                            e.y_root - self.root.winfo_y())

    def _do_drag(self, e):
        if self._drag_start:
            self.root.geometry(
                f"+{e.x_root - self._drag_start[0]}+{e.y_root - self._drag_start[1]}")

    def _stop_drag(self, e):
        self._drag_start = None

    # ── Active panel management ──────────────────────────────────────────────
    def _set_active_panel(self, panel):
        """Switch active gesture panel between 'music' and 'pdf'."""
        self._active_panel = panel
        self._update_panel_indicators()
        label = "🎵  MUSIC PANEL ACTIVE" if panel == "music" else "📄  PDF PANEL ACTIVE"
        self._gesture_strip.config(text=label, fg=ACCENT2)
        self.root.after(2500, lambda: self._gesture_strip.config(
            text="Waiting for gesture…", fg=TEXT_SEC))

    def _toggle_active_panel(self):
        new = "pdf" if self._active_panel == "music" else "music"
        self._set_active_panel(new)

    def _update_panel_indicators(self):
        """Update the colored tab/border on each panel header to show which is active."""
        if self._active_panel == "music":
            self._music_tab.config(bg=ACCENT, fg=ACCENT2)
            self._pdf_tab.config(bg=SURFACE, fg=TEXT_SEC)
        else:
            self._music_tab.config(bg=SURFACE, fg=TEXT_SEC)
            self._pdf_tab.config(bg=ACCENT, fg=ACCENT2)

    # ── UI build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.drag_bar = tk.Frame(self.root, bg=SURFACE, height=44, cursor="fleur")
        self.drag_bar.pack(fill="x")
        self.drag_bar.pack_propagate(False)

        tk.Label(self.drag_bar, text="DELTA MUSIC", font=("Georgia", 11, "bold"),
                 bg=SURFACE, fg=ACCENT, pady=12).pack(side="left", padx=20)

        close_btn = tk.Label(self.drag_bar, text="✕", font=("Helvetica", 12),
                             bg=SURFACE, fg=TEXT_SEC, cursor="hand2")
        close_btn.pack(side="right", padx=16)
        close_btn.bind("<Button-1>", lambda e: self.root.destroy())
        close_btn.bind("<Enter>",    lambda e: close_btn.config(fg="#E05C5C"))
        close_btn.bind("<Leave>",    lambda e: close_btn.config(fg=TEXT_SEC))

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True)

        left = tk.Frame(content, bg=BG, width=PLAYER_W)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Frame(content, bg=BORDER, width=1).pack(side="left", fill="y")

        right = tk.Frame(content, bg=PDF_BG, width=PDF_W)
        right.pack(side="left", fill="both", expand=True)
        right.pack_propagate(False)

        self._build_player(left)
        self._build_pdf_panel(right)

    # ── Player panel ─────────────────────────────────────────────────────────
    def _build_player(self, parent):
        self._build_sensor_panel(parent)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", side="bottom")
        self.status_label = tk.Label(
            parent, text="Ready", font=("Helvetica", 7),
            bg=SURFACE, fg=TEXT_SEC, anchor="w")
        self.status_label.pack(fill="x", side="bottom", padx=14, pady=4)

        # Panel active tab indicator
        self._music_tab = tk.Label(
            parent, text="● MUSIC PANEL", font=("Helvetica", 7, "bold"),
            bg=SURFACE, fg=TEXT_SEC, anchor="w", padx=12, pady=5,
            cursor="hand2")
        self._music_tab.pack(fill="x")
        self._music_tab.bind("<Button-1>", lambda e: self._set_active_panel("music"))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # Vinyl art
        art_frame = tk.Frame(parent, bg=BG, pady=16)
        art_frame.pack(fill="x")
        self.art_canvas = tk.Canvas(art_frame, width=160, height=160,
                                    bg=SURFACE, bd=0, highlightthickness=0)
        self.art_canvas.pack()
        self._draw_vinyl(self.art_canvas)

        # Track info
        info_frame = tk.Frame(parent, bg=BG)
        info_frame.pack(fill="x", padx=36)
        self.track_label = tk.Label(info_frame, text="No track selected",
                                    font=("Georgia", 13, "bold"), bg=BG, fg=TEXT_PRI,
                                    anchor="center", wraplength=308, justify="center")
        self.track_label.pack()
        self.sub_label = tk.Label(info_frame, text="Select a track below",
                                  font=("Helvetica", 9), bg=BG, fg=TEXT_SEC)
        self.sub_label.pack(pady=(4, 0))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=36, pady=10)

        # Playback controls
        ctrl = tk.Frame(parent, bg=BG)
        ctrl.pack()
        self._make_icon_btn(ctrl, "⏮", self.stop_music,  size=18).pack(side="left", padx=12)
        self._make_play_btn(ctrl).pack(side="left", padx=12)
        self._make_icon_btn(ctrl, "⏸", self.pause_music, size=18).pack(side="left", padx=12)

        # Volume row
        vol_frame = tk.Frame(parent, bg=BG, pady=8)
        vol_frame.pack(fill="x", padx=36)
        tk.Label(vol_frame, text="VOL", font=("Helvetica", 7, "bold"),
                 bg=BG, fg=TEXT_SEC).pack(side="left")
        self.volume_slider = tk.Scale(
            vol_frame, from_=0, to=100, orient="horizontal",
            command=self._on_volume_slider,
            bg=BG, fg=ACCENT, troughcolor=SLIDER_TR, activebackground=BTN_HOVER,
            highlightthickness=0, bd=0, showvalue=False,
            sliderrelief="flat", sliderlength=14, width=4)
        self.volume_slider.set(self._volume)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self._vol_readout = tk.Label(vol_frame, text=f"{self._volume}%",
                                     font=("Helvetica", 7), bg=BG, fg=TEXT_SEC,
                                     width=4, anchor="e")
        self._vol_readout.pack(side="left", padx=(6, 0))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=36, pady=(2, 0))

        self._build_playlist(parent)

    # ── Playlist ──────────────────────────────────────────────────────────────
    def _build_playlist(self, parent):
        BODY_H   = 130
        HEADER_H = 34
        TOTAL_H  = BODY_H + HEADER_H

        script_dir = os.path.dirname(os.path.abspath(__file__))

        outer = tk.Frame(parent, bg=BG, height=TOTAL_H)
        outer.pack(fill="x", padx=20, pady=(8, 0))
        outer.pack_propagate(False)

        hdr = tk.Frame(outer, bg=SURFACE, highlightbackground=BORDER,
                       highlightthickness=1, height=HEADER_H)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self._playlist_open  = False
        self._playlist_idx   = 0
        self._playlist_arrow = tk.StringVar(value="▸  PLAYLIST")

        toggle_lbl = tk.Label(hdr, textvariable=self._playlist_arrow,
                              font=("Helvetica", 8, "bold"), bg=SURFACE, fg=TEXT_SEC,
                              anchor="w", padx=12, pady=7, cursor="hand2")
        toggle_lbl.pack(side="left", fill="x", expand=True)
        tk.Label(hdr, text=f"{len(PLAYLIST)} tracks",
                 font=("Helvetica", 7), bg=SURFACE, fg=TEXT_SEC,
                 padx=10).pack(side="right")

        body = tk.Frame(outer, bg=SURFACE, highlightbackground=BORDER,
                        highlightthickness=1, height=BODY_H)
        body.pack_propagate(False)
        self._playlist_body = body

        self._list_canvas = tk.Canvas(body, bg=SURFACE, bd=0, highlightthickness=0)
        self._list_canvas.pack(side="left", fill="both", expand=True)
        vsb = tk.Scrollbar(body, orient="vertical", command=self._list_canvas.yview,
                           bg=SURFACE, troughcolor=BG, activebackground=ACCENT,
                           relief="flat", width=5)
        vsb.pack(side="right", fill="y")
        self._list_canvas.configure(yscrollcommand=vsb.set)

        inner = tk.Frame(self._list_canvas, bg=SURFACE)
        cw = self._list_canvas.create_window((0, 0), window=inner, anchor="nw")
        self._list_canvas.bind("<Configure>",
            lambda e: self._list_canvas.itemconfig(cw, width=e.width))
        inner.bind("<Configure>", lambda e: self._list_canvas.configure(
            scrollregion=self._list_canvas.bbox("all")))
        self._list_canvas.bind("<MouseWheel>",
            lambda e: self._list_canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._list_canvas.bind("<Button-4>",
            lambda e: self._list_canvas.yview_scroll(-1, "units"))
        self._list_canvas.bind("<Button-5>",
            lambda e: self._list_canvas.yview_scroll(1, "units"))

        self._track_row_widgets = []
        for idx, (name, fpath) in enumerate(PLAYLIST):
            if not os.path.isabs(fpath):
                fpath = os.path.join(script_dir, fpath)
            row = tk.Frame(inner, bg=SURFACE, cursor="hand2")
            row.pack(fill="x")
            num = tk.Label(row, text=f"{idx+1:02d}", font=("Helvetica", 8),
                           bg=SURFACE, fg=TEXT_SEC, width=3, anchor="e")
            num.pack(side="left", padx=(10, 4), pady=7)
            name_lbl = tk.Label(row, text=name, font=("Helvetica", 9),
                                bg=SURFACE, fg=TEXT_PRI, anchor="w")
            name_lbl.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", padx=10)

            self._track_row_widgets.append((row, num, name_lbl))

            def _enter(e, i=idx):
                if i != self._playlist_idx:
                    r, n, nl = self._track_row_widgets[i]
                    r.config(bg="#1E1E28"); n.config(bg="#1E1E28"); nl.config(bg="#1E1E28")
            def _leave(e, i=idx):
                if i != self._playlist_idx:
                    r, n, nl = self._track_row_widgets[i]
                    r.config(bg=SURFACE); n.config(bg=SURFACE); nl.config(bg=SURFACE)
            def _select(e, i=idx):
                self._set_playlist_highlight(i)
                self._load_track_by_idx(i)
            for w in (row, num, name_lbl):
                w.bind("<Enter>",    _enter)
                w.bind("<Leave>",    _leave)
                w.bind("<Button-1>", _select)

        def _toggle(e=None):
            if self._playlist_open:
                self._playlist_body.pack_forget()
                self._playlist_arrow.set("▸  PLAYLIST")
                self._playlist_open = False
            else:
                self._playlist_body.pack(fill="x")
                self._playlist_arrow.set("▾  PLAYLIST")
                self._playlist_open = True
                self._set_playlist_highlight(self._playlist_idx)

        toggle_lbl.bind("<Button-1>", _toggle)
        toggle_lbl.bind("<Enter>", lambda e: toggle_lbl.config(fg=ACCENT2))
        toggle_lbl.bind("<Leave>", lambda e: toggle_lbl.config(fg=TEXT_SEC))

    def _set_playlist_highlight(self, idx):
        for i, (row, num, name_lbl) in enumerate(self._track_row_widgets):
            if i == idx:
                row.config(bg=ACCENT);     num.config(bg=ACCENT,   fg=ACCENT2)
                name_lbl.config(bg=ACCENT, fg=ACCENT2)
            else:
                row.config(bg=SURFACE);    num.config(bg=SURFACE,  fg=TEXT_SEC)
                name_lbl.config(bg=SURFACE, fg=TEXT_PRI)
        if self._track_row_widgets:
            total_h = len(self._track_row_widgets) * 34
            if total_h > 0:
                frac = idx / len(self._track_row_widgets)
                self._list_canvas.yview_moveto(max(0, frac - 0.1))

    def _load_track_by_idx(self, idx):
        if not PLAYLIST or idx < 0 or idx >= len(PLAYLIST):
            return
        script_dir = os.path.dirname(os.path.abspath(__file__))
        name, fpath = PLAYLIST[idx]
        full = fpath if os.path.isabs(fpath) else os.path.join(script_dir, fpath)
        self._playlist_idx = idx
        self._load_track(full, name, close_playlist=False)

    def _load_track(self, path, name, close_playlist=True):
        self.current_file = path
        self.track_label.config(text=name)
        ext = os.path.splitext(path)[1].upper().lstrip(".")
        self.sub_label.config(text=f"{ext} file")
        self.paused = False
        if close_playlist and self._playlist_open:
            self._playlist_body.pack_forget()
            self._playlist_arrow.set("▸  PLAYLIST")
            self._playlist_open = False
        self.play_music()

    # ── Volume helpers ────────────────────────────────────────────────────────
    def _on_volume_slider(self, value):
        self._volume = int(value)
        self._vol_readout.config(text=f"{self._volume}%")
        if PYGAME_AVAILABLE:
            mixer.music.set_volume(self._volume / 100)

    def _set_volume(self, value):
        self._volume = max(0, min(100, value))
        self.volume_slider.set(self._volume)
        self._vol_readout.config(text=f"{self._volume}%")
        if PYGAME_AVAILABLE:
            mixer.music.set_volume(self._volume / 100)

    def volume_up(self):
        self._set_volume(self._volume + VOLUME_STEP)
        self._set_status(f"Volume: {self._volume}%")

    def volume_down(self):
        self._set_volume(self._volume - VOLUME_STEP)
        self._set_status(f"Volume: {self._volume}%")

    # ── Sensor status panel ───────────────────────────────────────────────────
    def _build_sensor_panel(self, parent):
        panel = tk.Frame(parent, bg=SURFACE)
        panel.pack(fill="x", side="bottom")
        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x")

        header = tk.Frame(panel, bg=SURFACE)
        header.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(header, text="GESTURE SENSORS", font=("Helvetica", 7, "bold"),
                 bg=SURFACE, fg=TEXT_SEC).pack(side="left")
        tk.Label(header,
                 text="● LIVE" if SENSORS_AVAILABLE else "● DEMO",
                 font=("Helvetica", 7, "bold"), bg=SURFACE,
                 fg="#4ADE80" if SENSORS_AVAILABLE else "#FACC15").pack(side="right")

        boxes_row = tk.Frame(panel, bg=SURFACE)
        boxes_row.pack(fill="x", padx=16, pady=(0, 6))
        self._left_box,  self._left_label,  self._left_dist  = self._make_sensor_box(boxes_row, "LEFT")
        self._right_box, self._right_label, self._right_dist = self._make_sensor_box(boxes_row, "RIGHT")

        self._gesture_strip = tk.Label(
            panel, text="Waiting for gesture…",
            font=("Helvetica", 8, "bold"), bg="#0F0F15", fg=TEXT_SEC,
            pady=6, anchor="center")
        self._gesture_strip.pack(fill="x", padx=16, pady=(0, 6))

        # Gesture reference legend — now includes panel-switch
        legend = tk.Frame(panel, bg=SURFACE)
        legend.pack(fill="x", padx=16, pady=(0, 8))
        refs = [
            ("Double Swipe  L↔R",  "Switch Music ↔ PDF panel"),
            ("Swipe L→R / R→L",    "🎵 Open/close playlist   📄 —"),
            ("Hold Left",           "🎵 Vol ▲ / Playlist ↑    📄 Prev page"),
            ("Hold Right",          "🎵 Vol ▼ / Playlist ↓    📄 Next page"),
            ("Hold Both",           "🎵 Stop / Confirm         📄 Zoom reset"),
        ]
        for g, a in refs:
            row = tk.Frame(legend, bg=SURFACE)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=g, font=("Helvetica", 6, "bold"),
                     bg=SURFACE, fg=ACCENT2, anchor="w", width=22).pack(side="left")
            tk.Label(row, text=a, font=("Helvetica", 6),
                     bg=SURFACE, fg=TEXT_SEC, anchor="w").pack(side="left")

    def _make_sensor_box(self, parent, label_text):
        box = tk.Frame(parent, bg=SENSOR_OFF,
                       highlightbackground=SENSOR_BORDER_OFF, highlightthickness=1,
                       width=148, height=68)
        box.pack(side="left", fill="x", expand=True,
                 padx=(0, 6) if label_text == "LEFT" else (6, 0))
        box.pack_propagate(False)
        inner = tk.Frame(box, bg=SENSOR_OFF)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        icon = tk.Label(inner, text="○", font=("Helvetica", 16),
                        bg=SENSOR_OFF, fg=TEXT_SEC)
        icon.pack()
        lbl = tk.Label(inner, text=label_text, font=("Helvetica", 7, "bold"),
                       bg=SENSOR_OFF, fg=TEXT_SEC)
        lbl.pack()
        dist = tk.Label(inner, text="—", font=("Helvetica", 7),
                        bg=SENSOR_OFF, fg=TEXT_SEC)
        dist.pack()
        box._inner = inner
        box._icon  = icon
        box._name  = lbl
        box._dist  = dist
        return box, lbl, dist

    def _set_sensor_state(self, box, state, dist_text="—"):
        colors = {
            "off":   (SENSOR_OFF,   SENSOR_BORDER_OFF, TEXT_SEC,  "○"),
            "on":    (SENSOR_ON,    SENSOR_BORDER_ON,  ACCENT2,   "●"),
            "swipe": (SENSOR_SWIPE, "#C084FC",         ACCENT2,   "↔"),
            "hold":  (SENSOR_HOLD,  "#E0AAFF",         "#0D0D0F", "✋"),
        }
        bg, border, fg, icon_char = colors.get(state, colors["off"])
        box.config(bg=bg, highlightbackground=border)
        box._inner.config(bg=bg)
        box._icon.config(bg=bg, fg=fg, text=icon_char)
        box._name.config(bg=bg, fg=fg)
        box._dist.config(bg=bg, fg=fg, text=dist_text)

    def _flash_gesture(self, which, state, message, duration_ms=600):
        box = self._left_box if which == "left" else self._right_box
        self._set_sensor_state(box, state)
        self._gesture_strip.config(text=message, fg=ACCENT2)
        self.root.after(duration_ms + 1500,
            lambda: self._gesture_strip.config(text="Waiting for gesture…", fg=TEXT_SEC))

    def _flash_both(self, state, message, duration_ms=700):
        self._set_sensor_state(self._left_box, state)
        self._set_sensor_state(self._right_box, state)
        self._gesture_strip.config(
            text=message,
            fg=SENSOR_HOLD if state == "hold" else ACCENT2)
        self.root.after(duration_ms + 2000,
            lambda: self._gesture_strip.config(text="Waiting for gesture…", fg=TEXT_SEC))

    # ── Sensor loop ───────────────────────────────────────────────────────────
    def _sensor_loop(self):
        sensor_left, sensor_right = init_sensors()
        swipe_stage      = 0
        swipe_dir        = None
        swipe_start_time = 0
        hold_left_start  = None
        hold_right_start = None
        hold_both_start  = None
        hold_left_fired  = False
        hold_right_fired = False
        hold_both_fired  = False
        vol_left_last_repeat  = 0
        vol_right_last_repeat = 0

        while self._gesture_running:
            left  = read_one(sensor_left)
            right = read_one(sensor_right)
            left_present  = left  != NO_READING and left  < PRESENT_MM
            right_present = right != NO_READING and right < PRESENT_MM
            dist_l = f"{left}mm"  if left  != NO_READING else "—"
            dist_r = f"{right}mm" if right != NO_READING else "—"
            now = time.monotonic()

            self.root.after(0, lambda lp=left_present, dl=dist_l:
                self._set_sensor_state(self._left_box, "on" if lp else "off", dl))
            self.root.after(0, lambda rp=right_present, dr=dist_r:
                self._set_sensor_state(self._right_box, "on" if rp else "off", dr))

            # ── Hold both ────────────────────────────────────────────────────
            if left_present and right_present:
                if hold_both_start is None:
                    hold_both_start = now
                if not hold_both_fired and now - hold_both_start >= HOLD_TIME:
                    hold_both_fired = True
                    self.root.after(0, lambda: self._flash_both(
                        "hold", "✋  HOLD BOTH — Stop / Confirm / Zoom Reset", 800))
                    self.root.after(0, self._on_gesture_hold_both)
            else:
                hold_both_start = None
                hold_both_fired = False

            # ── Hold left ────────────────────────────────────────────────────
            if left_present and not right_present:
                if hold_left_start is None:
                    hold_left_start      = now
                    vol_left_last_repeat = now
                if not hold_left_fired and now - hold_left_start >= HOLD_TIME:
                    hold_left_fired      = True
                    vol_left_last_repeat = now
                    self.root.after(0, lambda: self._flash_gesture(
                        "left", "hold",
                        "✋  HOLD LEFT — Vol ▲ / Playlist ↑  |  PDF: Prev Page", 800))
                    self.root.after(0, self._on_gesture_hold_left)
                elif hold_left_fired and self._active_panel == "music" and not self._playlist_open:
                    if now - vol_left_last_repeat >= VOLUME_HOLD_REPEAT_SEC:
                        vol_left_last_repeat = now
                        self.root.after(0, self.volume_up)
            else:
                hold_left_start = None
                hold_left_fired = False

            # ── Hold right ───────────────────────────────────────────────────
            if right_present and not left_present:
                if hold_right_start is None:
                    hold_right_start      = now
                    vol_right_last_repeat = now
                if not hold_right_fired and now - hold_right_start >= HOLD_TIME:
                    hold_right_fired      = True
                    vol_right_last_repeat = now
                    self.root.after(0, lambda: self._flash_gesture(
                        "right", "hold",
                        "✋  HOLD RIGHT — Vol ▼ / Playlist ↓  |  PDF: Next Page", 800))
                    self.root.after(0, self._on_gesture_hold_right)
                elif hold_right_fired and self._active_panel == "music" and not self._playlist_open:
                    if now - vol_right_last_repeat >= VOLUME_HOLD_REPEAT_SEC:
                        vol_right_last_repeat = now
                        self.root.after(0, self.volume_down)
            else:
                hold_right_start = None
                hold_right_fired = False

            # ── Swipe detection ───────────────────────────────────────────────
            if swipe_stage == 0:
                if left_present and (not right_present or left < right - DOMINANCE_MM):
                    swipe_stage      = 1
                    swipe_dir        = "LR"
                    swipe_start_time = now
                elif right_present and (not left_present or right < left - DOMINANCE_MM):
                    swipe_stage      = 1
                    swipe_dir        = "RL"
                    swipe_start_time = now
            elif swipe_stage == 1:
                if now - swipe_start_time > SWIPE_TIMEOUT:
                    swipe_stage = 0
                    swipe_dir   = None
                elif swipe_dir == "LR":
                    if right_present and (not left_present or right < left - DOMINANCE_MM):
                        completed_dir = swipe_dir
                        swipe_stage = 0
                        swipe_dir   = None
                        # ── Double-swipe check
                        if (now - self._last_swipe_time < DOUBLE_SWIPE_WINDOW and
                                self._last_swipe_dir == completed_dir):
                            self._last_swipe_time = 0
                            self._last_swipe_dir  = None
                            self.root.after(0, lambda: self._flash_gesture(
                                "right", "swipe", "⇒⇒  DOUBLE SWIPE — Switch Panel"))
                            self.root.after(0, self._toggle_active_panel)
                        else:
                            self._last_swipe_time = now
                            self._last_swipe_dir  = completed_dir
                            self.root.after(0, lambda: self._flash_gesture(
                                "right", "swipe", "→  SWIPE — Open / Close Playlist"))
                            self.root.after(0, self._on_gesture_swipe_lr)
                elif swipe_dir == "RL":
                    if left_present and (not right_present or left < right - DOMINANCE_MM):
                        completed_dir = swipe_dir
                        swipe_stage = 0
                        swipe_dir   = None
                        if (now - self._last_swipe_time < DOUBLE_SWIPE_WINDOW and
                                self._last_swipe_dir == completed_dir):
                            self._last_swipe_time = 0
                            self._last_swipe_dir  = None
                            self.root.after(0, lambda: self._flash_gesture(
                                "left", "swipe", "⇐⇐  DOUBLE SWIPE — Switch Panel"))
                            self.root.after(0, self._toggle_active_panel)
                        else:
                            self._last_swipe_time = now
                            self._last_swipe_dir  = completed_dir
                            self.root.after(0, lambda: self._flash_gesture(
                                "left", "swipe", "←  SWIPE — Open / Close Playlist"))
                            self.root.after(0, self._on_gesture_swipe_rl)

            time.sleep(0.02)

    # ── Demo loop ──────────────────────────────────────────────────────────────
    def _demo_sensor_loop(self):
        import random
        while self._gesture_running:
            state = random.choice(["none", "left", "right", "both"])
            lp = state in ("left", "both")
            rp = state in ("right", "both")
            dl = f"{random.randint(80, 280)}mm" if lp else "—"
            dr = f"{random.randint(80, 280)}mm" if rp else "—"
            self.root.after(0, lambda lp_=lp, dl_=dl:
                self._set_sensor_state(self._left_box,  "on" if lp_ else "off", dl_))
            self.root.after(0, lambda rp_=rp, dr_=dr:
                self._set_sensor_state(self._right_box, "on" if rp_ else "off", dr_))
            time.sleep(1.2)

    # ── Gesture handlers ──────────────────────────────────────────────────────
    #
    # MUSIC PANEL (playlist closed):
    #   Single Swipe     → open/close playlist
    #   Double Swipe     → switch to PDF panel
    #   Hold Left        → volume UP (repeats)
    #   Hold Right       → volume DOWN (repeats)
    #   Hold Both        → stop
    #
    # MUSIC PANEL (playlist open):
    #   Hold Left        → scroll highlight UP
    #   Hold Right       → scroll highlight DOWN
    #   Hold Both        → confirm / play selected
    #   Single Swipe     → close playlist
    #
    # PDF PANEL:
    #   Single Swipe     → (no action / could open pdf list)
    #   Double Swipe     → switch back to music panel
    #   Hold Left        → previous page
    #   Hold Right       → next page
    #   Hold Both        → reset zoom to 100%

    def _on_gesture_swipe_lr(self):
        if self._active_panel == "music":
            if self._playlist_open:
                self._close_playlist()
            else:
                self.open_file()

    def _on_gesture_swipe_rl(self):
        if self._active_panel == "music":
            if self._playlist_open:
                self._close_playlist()
            else:
                self.open_file()

    def _on_gesture_hold_left(self):
        if self._active_panel == "pdf":
            self.prev_page()
        elif self._playlist_open:
            self._playlist_scroll_up()
        else:
            self.volume_up()

    def _on_gesture_hold_right(self):
        if self._active_panel == "pdf":
            self.next_page()
        elif self._playlist_open:
            self._playlist_scroll_down()
        else:
            self.volume_down()

    def _on_gesture_hold_both(self):
        if self._active_panel == "pdf":
            self._pdf_zoom_reset()
        elif self._playlist_open:
            self._load_track_by_idx(self._playlist_idx)
            self._close_playlist()
        else:
            self.stop_music()

    def _close_playlist(self):
        if self._playlist_open:
            self._playlist_body.pack_forget()
            self._playlist_arrow.set("▸  PLAYLIST")
            self._playlist_open = False

    def _playlist_scroll_up(self):
        if not PLAYLIST:
            return
        new_idx = (self._playlist_idx - 1) % len(PLAYLIST)
        self._playlist_idx = new_idx
        self._set_playlist_highlight(new_idx)

    def _playlist_scroll_down(self):
        if not PLAYLIST:
            return
        new_idx = (self._playlist_idx + 1) % len(PLAYLIST)
        self._playlist_idx = new_idx
        self._set_playlist_highlight(new_idx)

    # ── PDF panel ──────────────────────────────────────────────────────────────
    def _build_pdf_panel(self, parent):
        header = tk.Frame(parent, bg=PDF_SURF, height=38)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="⧉  PDF VIEWER", font=("Georgia", 10, "bold"),
                 bg=PDF_SURF, fg=PDF_ACC, pady=10).pack(side="left", padx=16)

        tk.Frame(parent, bg="#3A2A50", height=1).pack(fill="x")

        # Panel active tab indicator (PDF side)
        self._pdf_tab = tk.Label(
            parent, text="● PDF PANEL", font=("Helvetica", 7, "bold"),
            bg=SURFACE, fg=TEXT_SEC, anchor="w", padx=12, pady=5,
            cursor="hand2")
        self._pdf_tab.pack(fill="x")
        self._pdf_tab.bind("<Button-1>", lambda e: self._set_active_panel("pdf"))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        toolbar = tk.Frame(parent, bg=PDF_SURF, height=34)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        nav_cfg = dict(font=("Helvetica", 11), bg=PDF_SURF, fg=TEXT_SEC, cursor="hand2")
        prev_btn = tk.Label(toolbar, text="◀", **nav_cfg)
        prev_btn.pack(side="left", padx=(12, 4))
        prev_btn.bind("<Button-1>", lambda e: self.prev_page())
        prev_btn.bind("<Enter>",    lambda e: prev_btn.config(fg=PDF_ACC))
        prev_btn.bind("<Leave>",    lambda e: prev_btn.config(fg=TEXT_SEC))

        self.page_label = tk.Label(toolbar, text="— / —", font=("Helvetica", 9),
                                   bg=PDF_SURF, fg=TEXT_SEC)
        self.page_label.pack(side="left", padx=4)

        next_btn = tk.Label(toolbar, text="▶", **nav_cfg)
        next_btn.pack(side="left", padx=(4, 12))
        next_btn.bind("<Button-1>", lambda e: self.next_page())
        next_btn.bind("<Enter>",    lambda e: next_btn.config(fg=PDF_ACC))
        next_btn.bind("<Leave>",    lambda e: next_btn.config(fg=TEXT_SEC))

        zm_cfg = dict(font=("Helvetica", 10, "bold"), bg=PDF_SURF, fg=TEXT_SEC, cursor="hand2")
        zoom_out = tk.Label(toolbar, text="−", **zm_cfg)
        zoom_out.pack(side="right", padx=(4, 12))
        zoom_out.bind("<Button-1>", lambda e: self.zoom_out())
        zoom_out.bind("<Enter>",    lambda e: zoom_out.config(fg=PDF_ACC))
        zoom_out.bind("<Leave>",    lambda e: zoom_out.config(fg=TEXT_SEC))

        self.zoom_label = tk.Label(toolbar, text="100%", font=("Helvetica", 9),
                                   bg=PDF_SURF, fg=TEXT_SEC)
        self.zoom_label.pack(side="right", padx=4)

        zoom_in = tk.Label(toolbar, text="+", **zm_cfg)
        zoom_in.pack(side="right", padx=(12, 4))
        zoom_in.bind("<Button-1>", lambda e: self.zoom_in())
        zoom_in.bind("<Enter>",    lambda e: zoom_in.config(fg=PDF_ACC))
        zoom_in.bind("<Leave>",    lambda e: zoom_in.config(fg=TEXT_SEC))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # ── PDF file dropdown (replaces old "Open PDF" button) ────────────────
        self._build_pdf_list(parent)

        canvas_frame = tk.Frame(parent, bg=PDF_BG)
        canvas_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.pdf_canvas = tk.Canvas(canvas_frame, bg=PDF_BG, bd=0, highlightthickness=0)
        self.pdf_canvas.pack(side="left", fill="both", expand=True)

        v_scroll = tk.Scrollbar(canvas_frame, orient="vertical",
                                command=self.pdf_canvas.yview,
                                bg=PDF_SURF, troughcolor=PDF_BG,
                                activebackground=PDF_ACC, relief="flat", width=6)
        v_scroll.pack(side="right", fill="y")
        self.pdf_canvas.configure(yscrollcommand=v_scroll.set)

        h_scroll = tk.Scrollbar(parent, orient="horizontal",
                                command=self.pdf_canvas.xview,
                                bg=PDF_SURF, troughcolor=PDF_BG,
                                activebackground=PDF_ACC, relief="flat", width=6)
        h_scroll.pack(fill="x", padx=6)
        self.pdf_canvas.configure(xscrollcommand=h_scroll.set)

        def _on_mousewheel(e):
            if e.state & 0x1:
                self.pdf_canvas.xview_scroll(-1*(e.delta//120), "units")
            else:
                self.pdf_canvas.yview_scroll(-1*(e.delta//120), "units")
        self.pdf_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.pdf_canvas.bind("<Button-4>",
            lambda e: self.pdf_canvas.xview_scroll(-1, "units") if (e.state & 0x1)
                      else self.pdf_canvas.yview_scroll(-1, "units"))
        self.pdf_canvas.bind("<Button-5>",
            lambda e: self.pdf_canvas.xview_scroll(1, "units") if (e.state & 0x1)
                      else self.pdf_canvas.yview_scroll(1, "units"))

        self._pan_last = None
        self.pdf_canvas.bind("<ButtonPress-2>", self._pan_start)
        self.pdf_canvas.bind("<B2-Motion>",     self._pan_move)
        self.pdf_canvas.bind("<ButtonPress-3>", self._pan_start)
        self.pdf_canvas.bind("<B3-Motion>",     self._pan_move)

        self._draw_pdf_placeholder()

    # ── PDF file list dropdown (styled like playlist) ─────────────────────────
    def _build_pdf_list(self, parent):
        """Collapsible PDF file list — same visual style as the music playlist."""
        BODY_H   = 100
        HEADER_H = 34
        TOTAL_H  = BODY_H + HEADER_H

        outer = tk.Frame(parent, bg=PDF_BG, height=TOTAL_H)
        outer.pack(fill="x", padx=6, pady=(4, 2))
        outer.pack_propagate(False)

        hdr = tk.Frame(outer, bg=PDF_SURF,
                       highlightbackground="#3A2A50", highlightthickness=1,
                       height=HEADER_H)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self._pdf_list_open  = False
        self._pdf_list_arrow = tk.StringVar(value="▸  PDF FILES")

        toggle_lbl = tk.Label(hdr, textvariable=self._pdf_list_arrow,
                              font=("Helvetica", 8, "bold"), bg=PDF_SURF, fg=TEXT_SEC,
                              anchor="w", padx=12, pady=7, cursor="hand2")
        toggle_lbl.pack(side="left", fill="x", expand=True)

        # "Open file…" sits in the header on the right — always visible
        open_lbl = tk.Label(hdr, text="+ Open…",
                            font=("Helvetica", 7, "bold"),
                            bg=PDF_SURF, fg=TEXT_SEC, padx=10, cursor="hand2")
        open_lbl.pack(side="right")
        open_lbl.bind("<Button-1>", lambda e: self.open_pdf())
        open_lbl.bind("<Enter>",    lambda e: open_lbl.config(fg=PDF_ACC))
        open_lbl.bind("<Leave>",    lambda e: open_lbl.config(fg=TEXT_SEC))

        body = tk.Frame(outer, bg=PDF_SURF,
                        highlightbackground="#3A2A50", highlightthickness=1,
                        height=BODY_H)
        body.pack_propagate(False)
        self._pdf_list_body = body

        self._pdf_list_canvas = tk.Canvas(body, bg=PDF_SURF, bd=0, highlightthickness=0)
        self._pdf_list_canvas.pack(side="left", fill="both", expand=True)
        vsb = tk.Scrollbar(body, orient="vertical",
                           command=self._pdf_list_canvas.yview,
                           bg=PDF_SURF, troughcolor=PDF_BG,
                           activebackground=PDF_ACC, relief="flat", width=5)
        vsb.pack(side="right", fill="y")
        self._pdf_list_canvas.configure(yscrollcommand=vsb.set)

        self._pdf_inner_frame = tk.Frame(self._pdf_list_canvas, bg=PDF_SURF)
        self._pdf_cw = self._pdf_list_canvas.create_window(
            (0, 0), window=self._pdf_inner_frame, anchor="nw")
        self._pdf_list_canvas.bind("<Configure>",
            lambda e: self._pdf_list_canvas.itemconfig(self._pdf_cw, width=e.width))
        self._pdf_inner_frame.bind("<Configure>",
            lambda e: self._pdf_list_canvas.configure(
                scrollregion=self._pdf_list_canvas.bbox("all")))

        self._pdf_placeholder = tk.Label(
            self._pdf_inner_frame,
            text="No PDFs opened yet — press + Open…",
            font=("Helvetica", 8), bg=PDF_SURF, fg=TEXT_SEC,
            anchor="w", padx=14, pady=10)

        self._pdf_row_widgets = []

        # Show hardcoded PDFs immediately, or placeholder if list is empty
        if self._recent_pdfs:
            self._refresh_pdf_list()
        else:
            self._pdf_placeholder.pack(fill="x")

        def _toggle(e=None):
            if self._pdf_list_open:
                self._pdf_list_body.pack_forget()
                self._pdf_list_arrow.set("▸  PDF FILES")
                self._pdf_list_open = False
            else:
                self._pdf_list_body.pack(fill="x")
                self._pdf_list_arrow.set("▾  PDF FILES")
                self._pdf_list_open = True

        toggle_lbl.bind("<Button-1>", _toggle)
        toggle_lbl.bind("<Enter>", lambda e: toggle_lbl.config(fg=ACCENT2))
        toggle_lbl.bind("<Leave>", lambda e: toggle_lbl.config(fg=TEXT_SEC))

    def _add_pdf_to_list(self, path):
        """Add or promote a PDF entry in the dropdown list."""
        name = os.path.basename(path)
        # Remove if already present (promote to top)
        self._recent_pdfs = [(n, p) for n, p in self._recent_pdfs if p != path]
        self._recent_pdfs.insert(0, (name, path))
        # Keep only 8 recent
        self._recent_pdfs = self._recent_pdfs[:8]
        self._refresh_pdf_list()
        # Auto-open the list when a new file is added
        if not self._pdf_list_open:
            self._pdf_list_body.pack(fill="x")
            self._pdf_list_arrow.set("▾  PDF FILES")
            self._pdf_list_open = True

    def _refresh_pdf_list(self):
        """Rebuild all rows in the PDF list from self._recent_pdfs."""
        # Clear existing rows
        for w in self._pdf_row_widgets:
            w[0].destroy()
        self._pdf_row_widgets = []

        if self._pdf_placeholder:
            self._pdf_placeholder.pack_forget()

        current_path = self.pdf_path

        for idx, (name, fpath) in enumerate(self._recent_pdfs):
            is_active = (fpath == current_path)
            row_bg = PDF_ACC if is_active else PDF_SURF

            row = tk.Frame(self._pdf_inner_frame, bg=row_bg, cursor="hand2")
            row.pack(fill="x")

            num = tk.Label(row, text=f"{idx+1:02d}",
                           font=("Helvetica", 8), bg=row_bg,
                           fg=ACCENT2 if is_active else TEXT_SEC,
                           width=3, anchor="e")
            num.pack(side="left", padx=(10, 4), pady=6)

            name_lbl = tk.Label(row, text=name, font=("Helvetica", 9),
                                bg=row_bg,
                                fg=ACCENT2 if is_active else TEXT_PRI,
                                anchor="w")
            name_lbl.pack(side="left", fill="x", expand=True, padx=(0, 10))

            # Page count badge if loaded
            if is_active and self.total_pages:
                pg_lbl = tk.Label(row, text=f"{self.total_pages}p",
                                  font=("Helvetica", 7), bg=row_bg,
                                  fg=ACCENT2, padx=6)
                pg_lbl.pack(side="right", padx=(0, 6))

            tk.Frame(self._pdf_inner_frame, bg="#2A2035", height=1).pack(fill="x", padx=10)

            self._pdf_row_widgets.append((row, num, name_lbl))

            def _enter(e, i=idx):
                if self._recent_pdfs[i][1] != current_path:
                    r, n_, nl = self._pdf_row_widgets[i]
                    r.config(bg="#22182E"); n_.config(bg="#22182E"); nl.config(bg="#22182E")

            def _leave(e, i=idx):
                if self._recent_pdfs[i][1] != current_path:
                    r, n_, nl = self._pdf_row_widgets[i]
                    r.config(bg=PDF_SURF); n_.config(bg=PDF_SURF); nl.config(bg=PDF_SURF)

            def _select(e, i=idx):
                self._load_pdf_by_idx(i)

            for w in (row, num, name_lbl):
                w.bind("<Enter>",    _enter)
                w.bind("<Leave>",    _leave)
                w.bind("<Button-1>", _select)

    def _load_pdf_by_idx(self, idx):
        if idx < 0 or idx >= len(self._recent_pdfs):
            return
        _, fpath = self._recent_pdfs[idx]
        self._open_pdf_path(fpath)

    def _draw_pdf_placeholder(self):
        self.pdf_canvas.delete("all")
        cw = PDF_W - 20
        ch = WIN_H - 44 - 1 - 38 - 34 - 1 - 24 - 12
        self.pdf_canvas.create_text(cw // 2, ch // 2,
                                    text="Open a PDF to view it here",
                                    font=("Helvetica", 11), fill=TEXT_SEC, anchor="center")

    # ── Drawing helpers ────────────────────────────────────────────────────────
    def _draw_vinyl(self, canvas):
        cx, cy, r = 80, 80, 70
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="#1C1C20", outline=BORDER, width=2)
        for i in range(3):
            gr = r - 12 - i*10
            canvas.create_oval(cx-gr, cy-gr, cx+gr, cy+gr, fill="", outline="#222228", width=1)
        lr = 22
        canvas.create_oval(cx-lr, cy-lr, cx+lr, cy+lr, fill=SURFACE, outline=BORDER, width=1)
        canvas.create_text(cx, cy, text="♬", font=("Helvetica", 16), fill=ACCENT)

    def _make_icon_btn(self, parent, symbol, cmd, size=16):
        lbl = tk.Label(parent, text=symbol, font=("Helvetica", size),
                       bg=BG, fg=TEXT_SEC, cursor="hand2")
        lbl.bind("<Button-1>", lambda e: cmd())
        lbl.bind("<Enter>",    lambda e: lbl.config(fg=ACCENT2))
        lbl.bind("<Leave>",    lambda e: lbl.config(fg=TEXT_SEC))
        return lbl

    def _make_play_btn(self, parent):
        canvas = tk.Canvas(parent, width=54, height=54, bg=BG, bd=0,
                           highlightthickness=0, cursor="hand2")
        canvas.create_oval(0, 0, 54, 54, fill=BTN_PLAY, outline="")
        canvas.create_polygon(20, 14, 20, 40, 42, 27, fill=BG, outline="")
        canvas.bind("<Button-1>", lambda e: self.play_music())
        canvas.bind("<Enter>", lambda e: canvas.itemconfig(1, fill=BTN_HOVER))
        canvas.bind("<Leave>", lambda e: canvas.itemconfig(1, fill=BTN_PLAY))
        return canvas

    # ── Playback ──────────────────────────────────────────────────────────────
    def open_file(self):
        if not self._playlist_open:
            self._playlist_body.pack(fill="x")
            self._playlist_arrow.set("▾  PLAYLIST")
            self._playlist_open = True
            self._set_playlist_highlight(self._playlist_idx)

    def play_music(self):
        if not PYGAME_AVAILABLE or not self.current_file:
            return
        if self.paused:
            mixer.music.unpause()
            self.paused = False
        else:
            mixer.music.load(self.current_file)
            mixer.music.play()

    def pause_music(self):
        if not PYGAME_AVAILABLE:
            return
        if not self.paused:
            mixer.music.pause()
            self.paused = True
        else:
            mixer.music.unpause()
            self.paused = False

    def stop_music(self):
        if not PYGAME_AVAILABLE:
            return
        mixer.music.stop()
        self.paused = False

    def set_volume(self, value):
        if PYGAME_AVAILABLE:
            mixer.music.set_volume(int(value) / 100)

    def _set_status(self, msg):
        self.status_label.config(text=msg)
        self.root.after(3000, lambda: self.status_label.config(text="Ready"))

    # ── PDF ────────────────────────────────────────────────────────────────────
    def open_pdf(self):
        path = filedialog.askopenfilename(
            filetypes=[("PDF Files", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        self._open_pdf_path(path)

    def _open_pdf_path(self, path):
        if not PYMUPDF_AVAILABLE:
            self._set_status("PyMuPDF not installed. Run: pip install pymupdf")
            return
        if not PIL_AVAILABLE:
            self._set_status("Pillow not installed. Run: pip install pillow")
            return
        try:
            self.pdf_doc     = fitz.open(path)
            self.pdf_path    = path
            self.current_page = 0
            self.total_pages  = len(self.pdf_doc)
            self.zoom_level   = 1.0
            self.zoom_label.config(text="100%")
            self._render_page()
            self._set_status(
                f"Opened: {os.path.basename(path)} ({self.total_pages} pages)")
            # Add to dropdown and refresh highlighting
            self._add_pdf_to_list(path)
            # Switch active panel to PDF automatically
            self._set_active_panel("pdf")
        except Exception as ex:
            self._set_status(f"Error opening PDF: {ex}")

    def _pdf_zoom_reset(self):
        if self.pdf_doc:
            self.zoom_level = 1.0
            self.zoom_label.config(text="100%")
            self._render_page()
            self._set_status("Zoom reset to 100%")

    def _render_page(self):
        if not self.pdf_doc or not PYMUPDF_AVAILABLE or not PIL_AVAILABLE:
            return
        page  = self.pdf_doc[self.current_page]
        scale = 1.5 * self.zoom_level
        mat   = fitz.Matrix(scale, scale)
        pix   = page.get_pixmap(matrix=mat, alpha=False)
        img   = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        photo = ImageTk.PhotoImage(img)
        self._pdf_img_ref = photo
        pad = 20
        self.pdf_canvas.delete("all")
        self.pdf_canvas.create_image(pad, pad, anchor="nw", image=photo)
        self.pdf_canvas.configure(
            scrollregion=(0, 0, img.width + pad * 2, img.height + pad * 2))
        self.pdf_canvas.yview_moveto(0)
        self.pdf_canvas.xview_moveto(0)
        self.page_label.config(
            text=f"{self.current_page + 1} / {self.total_pages}")

    def _pan_start(self, e):
        self._pan_last = (e.x, e.y)

    def _pan_move(self, e):
        if self._pan_last:
            dx = self._pan_last[0] - e.x
            dy = self._pan_last[1] - e.y
            self.pdf_canvas.xview_scroll(dx, "pixels")
            self.pdf_canvas.yview_scroll(dy, "pixels")
            self._pan_last = (e.x, e.y)

    def next_page(self):
        if self.pdf_doc and self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_page()

    def prev_page(self):
        if self.pdf_doc and self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def zoom_in(self):
        if self.zoom_level < 4.0:
            self.zoom_level = round(self.zoom_level + 0.25, 2)
            self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")
            self._render_page()

    def zoom_out(self):
        if self.zoom_level > 0.25:
            self.zoom_level = round(self.zoom_level - 0.25, 2)
            self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")
            self._render_page()

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = MusicPlayer(root)
    root.mainloop()
