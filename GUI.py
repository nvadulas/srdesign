import tkinter as tk
from tkinter import filedialog
import os

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

# Color Hex Codes
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

PLAYER_W  = 380
PDF_W     = 520
WIN_H     = 820


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

        self._build_ui()
        self._remove_title_bar()

    # Window drag
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
            x = e.x_root - self._drag_start[0]
            y = e.y_root - self._drag_start[1]
            self.root.geometry(f"+{x}+{y}")

    def _stop_drag(self, e):
        self._drag_start = None

    # UI
    def _build_ui(self):
        # Title bar (spans full width)
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

        # Two-column layout
        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True)

        # Left: music player
        left = tk.Frame(content, bg=BG, width=PLAYER_W)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        # Divider
        tk.Frame(content, bg=BORDER, width=1).pack(side="left", fill="y")

        # Right: PDF viewer
        right = tk.Frame(content, bg=PDF_BG, width=PDF_W)
        right.pack(side="left", fill="both", expand=True)
        right.pack_propagate(False)

        self._build_player(left)
        self._build_pdf_panel(right)

    # Player panel
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

        # Status
        self.status_label = tk.Label(
            parent, text="Ready",
            font=("Helvetica", 7), bg=SURFACE, fg=TEXT_SEC, anchor="w")
        self.status_label.pack(fill="x", side="bottom", padx=14, pady=4)

    # PDF panel
    def _build_pdf_panel(self, parent):
        # Header
        header = tk.Frame(parent, bg=PDF_SURF, height=38)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="⧉  PDF VIEWER", font=("Georgia", 10, "bold"),
                 bg=PDF_SURF, fg=PDF_ACC, pady=10).pack(side="left", padx=16)

        btn_cfg = dict(font=("Helvetica", 8, "bold"), bg=PDF_SURF,
                       fg=TEXT_SEC, cursor="hand2")

        open_pdf_lbl = tk.Label(header, text="Open PDF", **btn_cfg)
        open_pdf_lbl.pack(side="right", padx=12)
        open_pdf_lbl.bind("<Button-1>", lambda e: self.open_pdf())
        open_pdf_lbl.bind("<Enter>",    lambda e: open_pdf_lbl.config(fg=PDF_ACC))
        open_pdf_lbl.bind("<Leave>",    lambda e: open_pdf_lbl.config(fg=TEXT_SEC))

        tk.Frame(parent, bg="#3A2A50", height=1).pack(fill="x")

        # Toolbar: page nav + zoom
        toolbar = tk.Frame(parent, bg=PDF_SURF, height=34)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        nav_cfg = dict(font=("Helvetica", 11), bg=PDF_SURF,
                       fg=TEXT_SEC, cursor="hand2")

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

        # Zoom
        zm_cfg = dict(font=("Helvetica", 10, "bold"), bg=PDF_SURF,
                      fg=TEXT_SEC, cursor="hand2")
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

        # PDF file name bar
        self.pdf_name_label = tk.Label(
            parent, text="No PDF open",
            font=("Helvetica", 8), bg=PDF_BG, fg=TEXT_SEC, anchor="w")
        self.pdf_name_label.pack(fill="x", padx=14, pady=(6, 2))

        # Scrollable canvas area for PDF page
        canvas_frame = tk.Frame(parent, bg=PDF_BG)
        canvas_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.pdf_canvas = tk.Canvas(canvas_frame, bg=PDF_BG,
                                    bd=0, highlightthickness=0)
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

        # Mousewheel: vertical scroll, Shift+scroll = horizontal
        def _on_mousewheel(e):
            if e.state & 0x1:
                self.pdf_canvas.xview_scroll(-1*(e.delta//120), "units")
            else:
                self.pdf_canvas.yview_scroll(-1*(e.delta//120), "units")
        self.pdf_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.pdf_canvas.bind("<Shift-MouseWheel>",
            lambda e: self.pdf_canvas.xview_scroll(-1*(e.delta//120), "units"))
        # Linux scroll events
        self.pdf_canvas.bind("<Button-4>",
            lambda e: self.pdf_canvas.xview_scroll(-1, "units") if (e.state & 0x1) else self.pdf_canvas.yview_scroll(-1, "units"))
        self.pdf_canvas.bind("<Button-5>",
            lambda e: self.pdf_canvas.xview_scroll(1, "units") if (e.state & 0x1) else self.pdf_canvas.yview_scroll(1, "units"))
        self.pdf_canvas.bind("<Shift-Button-4>",
            lambda e: self.pdf_canvas.xview_scroll(-1, "units"))
        self.pdf_canvas.bind("<Shift-Button-5>",
            lambda e: self.pdf_canvas.xview_scroll(1, "units"))
        # Middle/right click drag to pan
        self._pan_last = None
        self.pdf_canvas.bind("<ButtonPress-2>", self._pan_start)
        self.pdf_canvas.bind("<B2-Motion>",     self._pan_move)
        self.pdf_canvas.bind("<ButtonPress-3>", self._pan_start)
        self.pdf_canvas.bind("<B3-Motion>",     self._pan_move)

        # Placeholder message
        self._draw_pdf_placeholder()

    def _draw_pdf_placeholder(self):
        self.pdf_canvas.delete("all")
        cw = PDF_W - 20
        ch = WIN_H - 44 - 1 - 38 - 34 - 1 - 24 - 12
        self.pdf_canvas.create_text(
            cw // 2, ch // 2,
            text="Open a PDF to view it here",
            font=("Helvetica", 11), fill=TEXT_SEC, anchor="center")

    # Drawing helpers
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

    # Playback
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

    # PDF
    def open_pdf(self):
        path = filedialog.askopenfilename(
            filetypes=[("PDF Files", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        if not PYMUPDF_AVAILABLE:
            self._set_status("PyMuPDF not installed. Run: pip install pymupdf")
            self.pdf_name_label.config(
                text="Install PyMuPDF: pip install pymupdf")
            return
        if not PIL_AVAILABLE:
            self._set_status("Pillow not installed. Run: pip install pillow")
            self.pdf_name_label.config(
                text="Install Pillow: pip install pillow")
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
            self._set_status(
                f"Opened: {os.path.basename(path)} ({self.total_pages} pages)")
        except Exception as ex:
            self._set_status(f"Error opening PDF: {ex}")

    def _render_page(self):
        if not self.pdf_doc or not PYMUPDF_AVAILABLE or not PIL_AVAILABLE:
            return
        page = self.pdf_doc[self.current_page]
        # Base scale of 1.5 for readability; zoom_level multiplies on top
        scale = 1.5 * self.zoom_level
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        photo = ImageTk.PhotoImage(img)
        self._pdf_img_ref = photo  # prevent GC

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


if __name__ == "__main__":
    root = tk.Tk()
    app = MusicPlayer(root)
    root.mainloop()


# For TOF SENSOR Gestures
# - Music Player Section
# -- Open Music File > Play Button > Pause Button > Back Track Button > Volume Control (up and down)

# - PDF Viewer Section
# -- Open PDF > Zoom in > Zoom Out > Scroll up and down > Scroll left and right > Previous or Next Page


