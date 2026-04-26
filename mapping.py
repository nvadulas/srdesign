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

# ── Sensor imports (graceful fallback for dev without hardware) ────────────────
try:
    import board
    import busio
    import digitalio
    import adafruit_vl53l1x
    SENSORS_AVAILABLE = True
except (ImportError, NotImplementedError):
    SENSORS_AVAILABLE = False

# ── Color palette ─────────────────────────────────────────────────────────────
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

# Sensor indicator colors
SENSOR_OFF     = "#1A1A20"   # inactive background
SENSOR_ON      = "#6F2DA8"   # hand detected — purple glow
SENSOR_SWIPE   = "#9B59D0"   # brief flash on swipe
SENSOR_HOLD    = "#C084FC"   # hold — brighter lavender
SENSOR_BORDER_OFF = "#2A2A35"
SENSOR_BORDER_ON  = "#9B59D0"

PLAYER_W  = 380
PDF_W     = 520
WIN_H     = 820

# ── Sensor / gesture constants ─────────────────────────────────────────────────
XSHUT_LEFT_PIN  = None   # set below if hardware available
XSHUT_RIGHT_PIN = None
PRESENT_MM    = 300
DOMINANCE_MM  = 40
SWIPE_TIMEOUT = 0.5
HOLD_TIME     = 3.0
NO_READING    = 65535

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

        # Gesture feedback state (thread → main thread via after())
        self._gesture_running = True
        self._left_dist_var   = tk.StringVar(value="—")
        self._right_dist_var  = tk.StringVar(value="—")

        self._build_ui()
        self._remove_title_bar()

        # Start sensor thread
        if SENSORS_AVAILABLE:
            t = threading.Thread(target=self._sensor_loop, daemon=True)
            t.start()
        else:
            # Demo mode: simulate random presence for UI testing
            t = threading.Thread(target=self._demo_sensor_loop, daemon=True)
            t.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self._gesture_running = False
        self.root.destroy()

    # ── Window drag ───────────────────────────────────────────────────────────
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
            self.root.geometry(f"+{e.x_root - self._drag_start[0]}+{e.y_root - self._drag_start[1]}")

    def _stop_drag(self, e):
        self._drag_start = None

    # ── UI build ──────────────────────────────────────────────────────────────
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

    # ── Player panel ──────────────────────────────────────────────────────────
    def _build_player(self, parent):
        art_frame = tk.Frame(parent, bg=BG, pady=22)
        art_frame.pack(fill="x")
        self.art_canvas = tk.Canvas(art_frame, width=160, height=160,
                                    bg=SURFACE, bd=0, highlightthickness=0)
        self.art_canvas.pack()
        self._draw_vinyl(self.art_canvas)

        info_frame = tk.Frame(parent, bg=BG)
        info_frame.pack(fill="x", padx=36)
        self.track_label = tk.Label(info_frame, text="No track selected",
                                    font=("Georgia", 13, "bold"),
                                    bg=BG, fg=TEXT_PRI, anchor="center",
                                    wraplength=308, justify="center")
        self.track_label.pack()
        self.sub_label = tk.Label(info_frame, text="Open a file to begin",
                                  font=("Helvetica", 9), bg=BG, fg=TEXT_SEC)
        self.sub_label.pack(pady=(4, 0))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=36, pady=16)

        ctrl = tk.Frame(parent, bg=BG)
        ctrl.pack()
        self._make_icon_btn(ctrl, "⏮", self.stop_music,  size=18).pack(side="left", padx=12)
        self._make_play_btn(ctrl).pack(side="left", padx=12)
        self._make_icon_btn(ctrl, "⏸", self.pause_music, size=18).pack(side="left", padx=12)

        open_row = tk.Frame(parent, bg=BG)
        open_row.pack(pady=(14, 0))
        open_btn = tk.Label(open_row, text="⊕  Open Music File",
                            font=("Helvetica", 9, "bold"),
                            bg=BORDER, fg=TEXT_SEC, padx=16, pady=8, cursor="hand2")
        open_btn.pack()
        open_btn.bind("<Button-1>", lambda e: self.open_file())
        open_btn.bind("<Enter>",    lambda e: open_btn.config(fg=ACCENT2))
        open_btn.bind("<Leave>",    lambda e: open_btn.config(fg=TEXT_SEC))

        vol_frame = tk.Frame(parent, bg=BG, pady=16)
        vol_frame.pack(fill="x", padx=36)
        tk.Label(vol_frame, text="VOL", font=("Helvetica", 7, "bold"),
                 bg=BG, fg=TEXT_SEC).pack(side="left")
        self.volume_slider = tk.Scale(
            vol_frame, from_=0, to=100, orient="horizontal",
            command=self.set_volume,
            bg=BG, fg=ACCENT, troughcolor=SLIDER_TR,
            activebackground=BTN_HOVER, highlightthickness=0,
            bd=0, showvalue=False, sliderrelief="flat",
            sliderlength=14, width=4)
        self.volume_slider.set(50)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=(10, 0))

        # ── Sensor status panel (at the bottom of the player column) ──────────
        self._build_sensor_panel(parent)

        # Status bar — pushed to very bottom
        self.status_label = tk.Label(
            parent, text="Ready",
            font=("Helvetica", 7), bg=SURFACE, fg=TEXT_SEC, anchor="w")
        self.status_label.pack(fill="x", side="bottom", padx=14, pady=4)

        # Thin divider above status
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", side="bottom")

    # ── Sensor status panel ───────────────────────────────────────────────────
    def _build_sensor_panel(self, parent):
        """Two sensor boxes + gesture event label, flush to the bottom of the player."""

        # Outer container — pushed to bottom, sits above status bar
        panel = tk.Frame(parent, bg=SURFACE)
        panel.pack(fill="x", side="bottom", padx=0, pady=0)

        # Top border line
        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x")

        # Header row
        header = tk.Frame(panel, bg=SURFACE)
        header.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(header, text="GESTURE SENSORS",
                 font=("Helvetica", 7, "bold"), bg=SURFACE, fg=TEXT_SEC).pack(side="left")
        self._sensor_hw_label = tk.Label(
            header,
            text="● LIVE" if SENSORS_AVAILABLE else "● DEMO",
            font=("Helvetica", 7, "bold"),
            bg=SURFACE,
            fg="#4ADE80" if SENSORS_AVAILABLE else "#FACC15")
        self._sensor_hw_label.pack(side="right")

        # Two indicator boxes
        boxes_row = tk.Frame(panel, bg=SURFACE)
        boxes_row.pack(fill="x", padx=16, pady=(0, 8))

        self._left_box,  self._left_label,  self._left_dist  = self._make_sensor_box(boxes_row, "LEFT")
        self._right_box, self._right_label, self._right_dist = self._make_sensor_box(boxes_row, "RIGHT")

        # Gesture event text strip
        self._gesture_strip = tk.Label(
            panel,
            text="Waiting for gesture…",
            font=("Helvetica", 8, "bold"),
            bg="#0F0F15", fg=TEXT_SEC,
            pady=7, anchor="center")
        self._gesture_strip.pack(fill="x", padx=16, pady=(0, 10))

    def _make_sensor_box(self, parent, label_text):
        """Creates one sensor indicator box. Returns (box_frame, label, dist_label)."""
        box = tk.Frame(parent, bg=SENSOR_OFF,
                       highlightbackground=SENSOR_BORDER_OFF,
                       highlightthickness=1,
                       width=148, height=72)
        box.pack(side="left", fill="x", expand=True, padx=(0, 6) if label_text == "LEFT" else (6, 0))
        box.pack_propagate(False)

        inner = tk.Frame(box, bg=SENSOR_OFF)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        icon = tk.Label(inner, text="○", font=("Helvetica", 16),
                        bg=SENSOR_OFF, fg=TEXT_SEC)
        icon.pack()

        lbl = tk.Label(inner, text=label_text,
                       font=("Helvetica", 7, "bold"),
                       bg=SENSOR_OFF, fg=TEXT_SEC)
        lbl.pack()

        dist = tk.Label(inner, text="—",
                        font=("Helvetica", 7),
                        bg=SENSOR_OFF, fg=TEXT_SEC)
        dist.pack()

        # Store inner widgets for recoloring
        box._inner  = inner
        box._icon   = icon
        box._name   = lbl
        box._dist   = dist
        return box, lbl, dist

    def _set_sensor_state(self, box, state, dist_text="—"):
        """
        state: 'off' | 'on' | 'swipe' | 'hold'
        Recolors box + all inner labels.
        """
        colors = {
            "off":   (SENSOR_OFF,   SENSOR_BORDER_OFF, TEXT_SEC, "○"),
            "on":    (SENSOR_ON,    SENSOR_BORDER_ON,  ACCENT2,  "●"),
            "swipe": (SENSOR_SWIPE, "#C084FC",         ACCENT2,  "↔"),
            "hold":  (SENSOR_HOLD,  "#E0AAFF",         "#0D0D0F","✋"),
        }
        bg, border, fg, icon_char = colors.get(state, colors["off"])

        box.config(bg=bg, highlightbackground=border)
        box._inner.config(bg=bg)
        box._icon.config(bg=bg, fg=fg, text=icon_char)
        box._name.config(bg=bg, fg=fg)
        box._dist.config(bg=bg, fg=fg, text=dist_text)

    def _flash_gesture(self, which, state, message, duration_ms=600):
        """Briefly flash a sensor box to 'swipe' or 'hold', then revert to 'on'/'off'."""
        box = self._left_box if which == "left" else self._right_box
        self._set_sensor_state(box, state)
        self._gesture_strip.config(text=message, fg=ACCENT2)
        self.root.after(duration_ms, lambda: self._restore_sensor(which))
        self.root.after(duration_ms + 1500,
                        lambda: self._gesture_strip.config(text="Waiting for gesture…", fg=TEXT_SEC))

    def _restore_sensor(self, which):
        """After a flash, restore box to whatever the current presence state is."""
        # This will be naturally corrected by the next sensor update loop tick

    def _flash_both(self, state, message, duration_ms=700):
        self._set_sensor_state(self._left_box, state)
        self._set_sensor_state(self._right_box, state)
        self._gesture_strip.config(text=message, fg=SENSOR_HOLD if state == "hold" else ACCENT2)
        self.root.after(duration_ms + 2000,
                        lambda: self._gesture_strip.config(text="Waiting for gesture…", fg=TEXT_SEC))

    # ── Sensor loop (runs in background thread) ────────────────────────────────
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

        while self._gesture_running:
            left  = read_one(sensor_left)
            right = read_one(sensor_right)

            left_present  = left  != NO_READING and left  < PRESENT_MM
            right_present = right != NO_READING and right < PRESENT_MM

            dist_l = f"{left}mm"  if left  != NO_READING else "—"
            dist_r = f"{right}mm" if right != NO_READING else "—"

            now = time.monotonic()

            # ── Update sensor boxes on the main thread ────────────────────────
            self.root.after(0, lambda lp=left_present, dl=dist_l: self._set_sensor_state(
                self._left_box,  "on" if lp else "off", dl))
            self.root.after(0, lambda rp=right_present, dr=dist_r: self._set_sensor_state(
                self._right_box, "on" if rp else "off", dr))

            # ── Hold detection ────────────────────────────────────────────────
            if left_present and right_present:
                if hold_both_start is None:
                    hold_both_start = now
                if not hold_both_fired and now - hold_both_start >= HOLD_TIME:
                    hold_both_fired = True
                    self.root.after(0, lambda: self._flash_both("hold", "✋  HOLD: Both sensors", 800))
                    self.root.after(0, self._on_gesture_hold_both)
            else:
                hold_both_start = None
                hold_both_fired = False

            if left_present and not right_present:
                if hold_left_start is None:
                    hold_left_start = now
                if not hold_left_fired and now - hold_left_start >= HOLD_TIME:
                    hold_left_fired = True
                    self.root.after(0, lambda: self._flash_gesture("left", "hold", "✋  HOLD: Left sensor", 800))
                    self.root.after(0, self._on_gesture_hold_left)
            else:
                hold_left_start = None
                hold_left_fired = False

            if right_present and not left_present:
                if hold_right_start is None:
                    hold_right_start = now
                if not hold_right_fired and now - hold_right_start >= HOLD_TIME:
                    hold_right_fired = True
                    self.root.after(0, lambda: self._flash_gesture("right", "hold", "✋  HOLD: Right sensor", 800))
                    self.root.after(0, self._on_gesture_hold_right)
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
                        swipe_stage = 0
                        swipe_dir   = None
                        self.root.after(0, lambda: self._flash_gesture("right", "swipe", "→  SWIPE: Left to Right"))
                        self.root.after(0, self._on_gesture_swipe_lr)
                elif swipe_dir == "RL":
                    if left_present and (not right_present or left < right - DOMINANCE_MM):
                        swipe_stage = 0
                        swipe_dir   = None
                        self.root.after(0, lambda: self._flash_gesture("left", "swipe", "←  SWIPE: Right to Left"))
                        self.root.after(0, self._on_gesture_swipe_rl)

            time.sleep(0.02)

    # ── Demo loop (no hardware) ────────────────────────────────────────────────
    def _demo_sensor_loop(self):
        """Cycles through fake sensor states so you can see the UI working."""
        import random
        states = ["none", "left", "right", "both"]
        while self._gesture_running:
            state = random.choice(states)
            lp = state in ("left", "both")
            rp = state in ("right", "both")
            dl = f"{random.randint(80, 280)}mm" if lp else "—"
            dr = f"{random.randint(80, 280)}mm" if rp else "—"
            self.root.after(0, lambda lp_=lp, dl_=dl: self._set_sensor_state(
                self._left_box,  "on" if lp_ else "off", dl_))
            self.root.after(0, lambda rp_=rp, dr_=dr: self._set_sensor_state(
                self._right_box, "on" if rp_ else "off", dr_))
            time.sleep(1.2)

    # ── Gesture action handlers (wire your commands here) ─────────────────────
    def _on_gesture_swipe_lr(self):
        """Left → Right swipe: next PDF page."""
        self.next_page()

    def _on_gesture_swipe_rl(self):
        """Right → Left swipe: previous PDF page."""
        self.prev_page()

    def _on_gesture_hold_left(self):
        """Left hold: pause/unpause music."""
        self.pause_music()

    def _on_gesture_hold_right(self):
        """Right hold: open music file dialog."""
        self.open_file()

    def _on_gesture_hold_both(self):
        """Both hold: stop music."""
        self.stop_music()

    # ── PDF panel ─────────────────────────────────────────────────────────────
    def _build_pdf_panel(self, parent):
        header = tk.Frame(parent, bg=PDF_SURF, height=38)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="⧉  PDF VIEWER", font=("Georgia", 10, "bold"),
                 bg=PDF_SURF, fg=PDF_ACC, pady=10).pack(side="left", padx=16)
        btn_cfg = dict(font=("Helvetica", 8, "bold"), bg=PDF_SURF, fg=TEXT_SEC, cursor="hand2")
        open_pdf_lbl = tk.Label(header, text="Open PDF", **btn_cfg)
        open_pdf_lbl.pack(side="right", padx=12)
        open_pdf_lbl.bind("<Button-1>", lambda e: self.open_pdf())
        open_pdf_lbl.bind("<Enter>",    lambda e: open_pdf_lbl.config(fg=PDF_ACC))
        open_pdf_lbl.bind("<Leave>",    lambda e: open_pdf_lbl.config(fg=TEXT_SEC))

        tk.Frame(parent, bg="#3A2A50", height=1).pack(fill="x")

        toolbar = tk.Frame(parent, bg=PDF_SURF, height=34)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)
        nav_cfg = dict(font=("Helvetica", 11), bg=PDF_SURF, fg=TEXT_SEC, cursor="hand2")
        prev_btn = tk.Label(toolbar, text="◀", **nav_cfg)
        prev_btn.pack(side="left", padx=(12, 4))
        prev_btn.bind("<Button-1>", lambda e: self.prev_page())
        prev_btn.bind("<Enter>",    lambda e: prev_btn.config(fg=PDF_ACC))
        prev_btn.bind("<Leave>",    lambda e: prev_btn.config(fg=TEXT_SEC))
        self.page_label = tk.Label(toolbar, text="— / —",
                                   font=("Helvetica", 9), bg=PDF_SURF, fg=TEXT_SEC)
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
        self.zoom_label = tk.Label(toolbar, text="100%",
                                   font=("Helvetica", 9), bg=PDF_SURF, fg=TEXT_SEC)
        self.zoom_label.pack(side="right", padx=4)
        zoom_in = tk.Label(toolbar, text="+", **zm_cfg)
        zoom_in.pack(side="right", padx=(12, 4))
        zoom_in.bind("<Button-1>", lambda e: self.zoom_in())
        zoom_in.bind("<Enter>",    lambda e: zoom_in.config(fg=PDF_ACC))
        zoom_in.bind("<Leave>",    lambda e: zoom_in.config(fg=TEXT_SEC))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")
        self.pdf_name_label = tk.Label(parent, text="No PDF open",
                                       font=("Helvetica", 8), bg=PDF_BG, fg=TEXT_SEC, anchor="w")
        self.pdf_name_label.pack(fill="x", padx=14, pady=(6, 2))

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
            lambda e: self.pdf_canvas.xview_scroll(-1, "units") if (e.state & 0x1) else self.pdf_canvas.yview_scroll(-1, "units"))
        self.pdf_canvas.bind("<Button-5>",
            lambda e: self.pdf_canvas.xview_scroll(1, "units") if (e.state & 0x1) else self.pdf_canvas.yview_scroll(1, "units"))
        self._pan_last = None
        self.pdf_canvas.bind("<ButtonPress-2>", self._pan_start)
        self.pdf_canvas.bind("<B2-Motion>",     self._pan_move)
        self.pdf_canvas.bind("<ButtonPress-3>", self._pan_start)
        self.pdf_canvas.bind("<B3-Motion>",     self._pan_move)

        self._draw_pdf_placeholder()

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
            canvas.create_oval(cx-gr, cy-gr, cx+gr, cy+gr,
                                fill="", outline="#222228", width=1)
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
        canvas = tk.Canvas(parent, width=54, height=54,
                           bg=BG, bd=0, highlightthickness=0, cursor="hand2")
        canvas.create_oval(0, 0, 54, 54, fill=BTN_PLAY, outline="")
        canvas.create_polygon(20, 14, 20, 40, 42, 27, fill=BG, outline="")
        canvas.bind("<Button-1>", lambda e: self.play_music())
        canvas.bind("<Enter>", lambda e: canvas.itemconfig(1, fill=BTN_HOVER))
        canvas.bind("<Leave>", lambda e: canvas.itemconfig(1, fill=BTN_PLAY))
        return canvas

    # ── Playback ──────────────────────────────────────────────────────────────
    def open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Audio Files", "*.mp3 *.wav *.ogg")])
        if path:
            self.current_file = path
            name = os.path.splitext(os.path.basename(path))[0]
            self.track_label.config(text=name)
            self.sub_label.config(
                text=os.path.splitext(path)[1].upper().lstrip(".") + " file")
            self.paused = False

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

    # ── PDF ───────────────────────────────────────────────────────────────────
    def open_pdf(self):
        path = filedialog.askopenfilename(
            filetypes=[("PDF Files", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        if not PYMUPDF_AVAILABLE:
            self._set_status("PyMuPDF not installed. Run: pip install pymupdf")
            return
        if not PIL_AVAILABLE:
            self._set_status("Pillow not installed. Run: pip install pillow")
            return
        try:
            self.pdf_doc = fitz.open(path)
            self.pdf_path = path
            self.current_page = 0
            self.total_pages = len(self.pdf_doc)
            self.zoom_level = 1.0
            self.zoom_label.config(text="100%")
            self.pdf_name_label.config(text=os.path.basename(path))
            self._render_page()
            self._set_status(f"Opened: {os.path.basename(path)} ({self.total_pages} pages)")
        except Exception as ex:
            self._set_status(f"Error opening PDF: {ex}")

    def _render_page(self):
        if not self.pdf_doc or not PYMUPDF_AVAILABLE or not PIL_AVAILABLE:
            return
        page = self.pdf_doc[self.current_page]
        scale = 1.5 * self.zoom_level
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        photo = ImageTk.PhotoImage(img)
        self._pdf_img_ref = photo
        pad = 20
        self.pdf_canvas.delete("all")
        self.pdf_canvas.create_image(pad, pad, anchor="nw", image=photo)
        self.pdf_canvas.configure(
            scrollregion=(0, 0, img.width + pad * 2, img.height + pad * 2))
        self.pdf_canvas.yview_moveto(0)
        self.pdf_canvas.xview_moveto(0)
        self.page_label.config(text=f"{self.current_page + 1} / {self.total_pages}")

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


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = MusicPlayer(root)
    root.mainloop()
