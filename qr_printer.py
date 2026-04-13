"""
QR Code 프린터 - Windows용
필요 패키지 설치
    pip install qrcode[pil] pillow pywin32

실행
    python qr_printer.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import qrcode
from PIL import Image, ImageTk, ImageDraw, ImageFont
import datetime
import os
import sys
import json
import tempfile
import threading
import subprocess
import urllib.request

VERSION = "1.3.0"
GITHUB_REPO = "smc5720/QR-Code-Printer"

# Windows 프린터 관련 (pywin32)
try:
    import win32print
    import win32ui
    import win32con
    from PIL import ImageWin
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


# ──────────────────────────────────────────────
#  자동 업데이트
# ──────────────────────────────────────────────

def _version_tuple(v: str):
    return tuple(int(x) for x in v.strip().lstrip("v").split("."))


def check_for_update():
    """GitHub Releases 최신 버전 확인. 새 버전이 있으면 dict, 없으면 None."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "QR-Code-Printer",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        latest = data["tag_name"]
        if _version_tuple(latest) > _version_tuple(VERSION):
            return {
                "version": latest.lstrip("v"),
                "assets": data.get("assets", []),
                "html_url": data["html_url"],
                "body": data.get("body", ""),
            }
    except Exception:
        pass
    return None


def _find_asset_url(assets: list):
    """현재 실행 형태(.exe / .py)에 맞는 에셋 URL, 이름, 크기 반환."""
    is_exe = getattr(sys, "frozen", False)
    target_ext = ".exe" if is_exe else ".py"
    for a in assets:
        if a["name"].lower().endswith(target_ext):
            return a["browser_download_url"], a["name"], a.get("size", 0)
    if assets:
        return assets[0]["browser_download_url"], assets[0]["name"], assets[0].get("size", 0)
    return None, None, 0


def _remove_zone_identifier(filepath: str):
    """Windows Zone.Identifier ADS를 제거하여 SmartScreen/Defender 차단 방지."""
    try:
        import ctypes
        ctypes.windll.kernel32.DeleteFileW(filepath + ":Zone.Identifier")
    except Exception:
        pass


def download_file(url: str, dest: str, progress_cb=None, expected_size: int = 0):
    """URL → dest 다운로드. progress_cb(downloaded, total) 호출."""
    req = urllib.request.Request(url, headers={"User-Agent": "QR-Code-Printer"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(downloaded, total)
    # 다운로드 검증
    actual_size = os.path.getsize(dest)
    if total > 0 and actual_size != total:
        os.unlink(dest)
        raise RuntimeError(f"다운로드 불완전: {actual_size}/{total} bytes")
    if expected_size > 0 and actual_size != expected_size:
        os.unlink(dest)
        raise RuntimeError(f"파일 크기 불일치: {actual_size}/{expected_size} bytes")
    if dest.lower().endswith((".exe", ".exe.new")):
        with open(dest, "rb") as f:
            if f.read(2) != b"MZ":
                os.unlink(dest)
                raise RuntimeError("다운로드된 파일이 유효한 실행 파일이 아닙니다.")
    # Zone.Identifier ADS 제거 (Windows Defender/SmartScreen 차단 방지)
    _remove_zone_identifier(dest)


def apply_update(new_file_path: str):
    """현재 실행 파일을 교체하고 재시작."""
    current = os.path.abspath(sys.argv[0])
    is_exe = getattr(sys, "frozen", False)

    if is_exe:
        # exe는 실행 중 잠김 → 배치 스크립트로 교체 후 재실행
        new_size = os.path.getsize(new_file_path)
        bat = current + ".update.bat"
        with open(bat, "w", encoding="utf-8") as f:
            f.write(
                f'@echo off\n'
                f'setlocal\n'
                f'set "RETRIES=0"\n'
                f':wait_loop\n'
                f'timeout /t 1 /nobreak >nul\n'
                f'set /a RETRIES+=1\n'
                f'if %RETRIES% GTR 30 (\n'
                f'    del "{new_file_path}" >nul 2>&1\n'
                f'    del "%~f0"\n'
                f'    exit /b 1\n'
                f')\n'
                f'move /y "{new_file_path}" "{current}" >nul 2>&1\n'
                f'if errorlevel 1 goto wait_loop\n'
                f'del /f "{current}:Zone.Identifier" >nul 2>&1\n'
                f'timeout /t 1 /nobreak >nul\n'
                f'start "" "{current}"\n'
                f'del "%~f0"\n'
            )
        subprocess.Popen(["cmd", "/c", bat],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        sys.exit(0)
    else:
        # py 파일은 직접 교체 가능
        os.replace(new_file_path, current)
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)


# ──────────────────────────────────────────────
#  폰트 로드 헬퍼
# ──────────────────────────────────────────────
FONT_PATHS = [
    "C:/Windows/Fonts/malgun.ttf",   # 맑은 고딕 (한국어)
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
]

def load_font(size: int):
    for fp in FONT_PATHS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ──────────────────────────────────────────────
#  핵심 로직
# ──────────────────────────────────────────────

def generate_unique_value():
    """현재 시간 기반 고유값 생성"""
    now = datetime.datetime.now()
    time_str = now.strftime("%Y%m%d-%H%M%S")
    micro = str(now.microsecond).zfill(6)[:6]
    return f"{time_str}-{micro}", now


def generate_qr_image(data: str, box_size: int = 10, border: int = 4) -> Image.Image:
    """QR 코드 이미지 생성"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def measure_text_block(text: str, font, pad_v: int, line_gap: int = 4) -> int:
    """여러 줄 텍스트 블록 전체 높이 계산"""
    if not text.strip():
        return 0
    lines = text.strip().splitlines()
    dummy = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(dummy)
    _, _, _, h = d.textbbox((0, 0), "A", font=font)
    return len(lines) * (h + line_gap) + pad_v * 2


def draw_centered_multiline(draw, x_center, y_start, text: str, font, fill, pad_v, line_gap=4):
    """텍스트를 수평 중앙 정렬 + 여러 줄로 그림, 마지막 y 반환"""
    lines = text.strip().splitlines()
    dummy = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(dummy)
    y = y_start + pad_v
    for line in lines:
        _, _, tw, th = d.textbbox((0, 0), line, font=font)
        draw.text((x_center - tw // 2, y), line, fill=fill, font=font)
        y += th + line_gap
    return y


def build_full_image(
    qr_img: Image.Image,
    unique_value: str,
    generated_at: datetime.datetime,
    top_text: str = "",
    bottom_text: str = "",
    scale: float = 1.0,
) -> Image.Image:
    """
    QR 코드 위아래에 문구를 추가한 최종 이미지 생성.

    레이아웃:
        ─────────────────────
        [상단 문구]   (top_text 있을 때만)
        ─────────────────────
        [QR 코드]
        ─────────────────────
        [ID]                  (항상 표시)
        ─────────────────────
        [하단 문구]   (bottom_text 있을 때만)
        ─────────────────────
    """
    W = qr_img.width

    fs_info    = max(12, int(13 * scale))
    fs_caption = max(14, int(17 * scale))
    pad_v      = max(6,  int(8  * scale))
    line_gap   = 4

    font_info    = load_font(fs_info)
    font_caption = load_font(fs_caption)

    info_text = f"ID: {unique_value}"

    top_h    = measure_text_block(top_text,    font_caption, pad_v, line_gap) if top_text.strip()    else 0
    info_h   = measure_text_block(info_text,   font_info,    pad_v, line_gap)
    bottom_h = measure_text_block(bottom_text, font_caption, pad_v, line_gap) if bottom_text.strip() else 0

    total_h = top_h + qr_img.height + info_h + bottom_h

    canvas = Image.new("RGB", (W, total_h), "white")
    draw   = ImageDraw.Draw(canvas)
    y = 0

    # 1) 상단 문구
    if top_text.strip():
        draw_centered_multiline(draw, W // 2, y, top_text, font_caption, "#111111", pad_v, line_gap)
        y += top_h
        draw.line([(0, y - 1), (W, y - 1)], fill="#CCCCCC", width=1)

    # 2) QR 코드
    canvas.paste(qr_img, (0, y))
    y += qr_img.height

    # 3) 고정 정보
    draw.line([(0, y), (W, y)], fill="#CCCCCC", width=1)
    draw_centered_multiline(draw, W // 2, y, info_text, font_info, "#333333", pad_v, line_gap)
    y += info_h

    # 4) 하단 문구
    if bottom_text.strip():
        draw.line([(0, y), (W, y)], fill="#CCCCCC", width=1)
        draw_centered_multiline(draw, W // 2, y, bottom_text, font_caption, "#111111", pad_v, line_gap)

    return canvas


# ──────────────────────────────────────────────
#  프린터
# ──────────────────────────────────────────────

def get_printers():
    if WIN32_AVAILABLE:
        printers = []
        for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        ):
            printers.append(p[2])
        return printers
    return ["(pywin32 미설치 - 가상 프린터)", "Microsoft Print to PDF"]


def print_image_win32(printer_name: str, img: Image.Image):
    if not WIN32_AVAILABLE:
        raise RuntimeError("pywin32가 설치되어 있지 않습니다.\npip install pywin32 를 실행하세요.")

    with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as tmp:
        tmp_path = tmp.name
    img.save(tmp_path, "BMP")

    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            hdc.StartDoc("QR Code")
            hdc.StartPage()

            px = hdc.GetDeviceCaps(win32con.HORZRES)
            py = hdc.GetDeviceCaps(win32con.VERTRES)

            iw, ih = img.size
            s = min(px / iw, py / ih) * 0.85
            dw, dh = int(iw * s), int(ih * s)
            xo = (px - dw) // 2
            yo = int(py * 0.05)

            dib = ImageWin.Dib(img)
            dib.draw(hdc.GetHandleOutput(), (xo, yo, xo + dw, yo + dh))

            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
        finally:
            win32print.ClosePrinter(hprinter)
    finally:
        os.unlink(tmp_path)


# ──────────────────────────────────────────────
#  설정 저장/불러오기
# ──────────────────────────────────────────────

def _config_path():
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        base = os.path.join(local_app_data, "QR-Code-Printer")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "qr_printer_config.json")
    # 폴백: 실행 파일과 같은 디렉토리
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, "qr_printer_config.json")


def _legacy_config_path():
    """기존 버전 호환: 실행 파일 옆 설정 파일 경로."""
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, "qr_printer_config.json")


def load_config():
    path = _config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 기존 위치에서 마이그레이션
    legacy = _legacy_config_path()
    if legacy != path and os.path.exists(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                data = json.load(f)
            save_config(data)
            os.remove(legacy)
            return data
        except Exception:
            pass
    return {}


def save_config(data):
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ──────────────────────────────────────────────
#  GUI
# ──────────────────────────────────────────────

class QRPrinterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"QR 코드 프린터  v{VERSION}")
        self.resizable(False, False)
        self.configure(bg="#F0F4F8")

        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
        self._icon_path = os.path.join(base, "icon.ico")
        if os.path.exists(self._icon_path):
            self.iconbitmap(self._icon_path)

        self._unique_value = None
        self._generated_at = None
        self._tk_img       = None

        self._build_ui()
        self._load_saved_texts()
        self._refresh_printers()
        self._generate()
        self.after(1000, self._check_update_background)

    def _card(self, parent, title: str):
        return tk.LabelFrame(parent, text=f" {title} ",
                             bg="#FFFFFF", fg="#1E293B",
                             font=("맑은 고딕", 10, "bold"),
                             relief="flat", bd=1,
                             highlightbackground="#CBD5E1",
                             highlightthickness=1)

    def _build_ui(self):
        BG     = "#F0F4F8"
        CARD   = "#FFFFFF"
        ACCENT = "#2563EB"

        # 타이틀
        tf = tk.Frame(self, bg=ACCENT, pady=10)
        tf.pack(fill="x")
        tk.Label(tf, text="🖨  QR 코드 프린터",
                 font=("맑은 고딕", 16, "bold"),
                 bg=ACCENT, fg="white").pack()

        main = tk.Frame(self, bg=BG, padx=16, pady=16)
        main.pack(fill="both", expand=True)

        # ── 프린터 선택 ──
        pf = self._card(main, "프린터 선택")
        pf.pack(fill="x", pady=(0, 10))
        ip = tk.Frame(pf, bg=CARD, padx=10, pady=8)
        ip.pack(fill="x")

        self.printer_var = tk.StringVar()
        self.printer_combo = ttk.Combobox(ip, textvariable=self.printer_var,
                                          state="readonly", width=38,
                                          font=("맑은 고딕", 10))
        self.printer_combo.pack(side="left", fill="x", expand=True)
        tk.Button(ip, text="↻ 새로고침",
                  command=self._refresh_printers,
                  bg="#E2E8F0", fg="#1E293B",
                  font=("맑은 고딕", 9), relief="flat",
                  padx=8, cursor="hand2"
                  ).pack(side="left", padx=(6, 0))

        # 출력 방향
        io = tk.Frame(pf, bg=CARD, padx=10, pady=(0, 8))
        io.pack(fill="x")
        tk.Label(io, text="출력 방향",
                 bg=CARD, font=("맑은 고딕", 9, "bold"), fg="#475569"
                 ).pack(side="left")
        self.orientation_var = tk.StringVar(value="portrait")
        tk.Radiobutton(io, text="세로", variable=self.orientation_var,
                       value="portrait", command=self._on_orientation_change,
                       bg=CARD, font=("맑은 고딕", 9), cursor="hand2"
                       ).pack(side="left", padx=(10, 0))
        tk.Radiobutton(io, text="가로", variable=self.orientation_var,
                       value="landscape", command=self._on_orientation_change,
                       bg=CARD, font=("맑은 고딕", 9), cursor="hand2"
                       ).pack(side="left", padx=(4, 0))

        # ── 문구 설정 ──
        lf = self._card(main, "문구 설정")
        lf.pack(fill="x", pady=(0, 10))
        il = tk.Frame(lf, bg=CARD, padx=10, pady=10)
        il.pack(fill="x")

        label_style = dict(bg=CARD, font=("맑은 고딕", 9, "bold"),
                           fg="#475569", width=8, anchor="nw")
        text_style  = dict(height=2, width=36, font=("맑은 고딕", 10),
                           relief="solid", bd=1, highlightthickness=0)

        tk.Label(il, text="상단 문구", **label_style).grid(row=0, column=0, sticky="nw", pady=(0, 6))
        self.top_text = tk.Text(il, **text_style)
        self.top_text.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        self.top_text.bind("<KeyRelease>", lambda e: self._on_text_change())

        tk.Label(il, text="하단 문구", **label_style).grid(row=1, column=0, sticky="nw")
        self.bottom_text = tk.Text(il, **text_style)
        self.bottom_text.grid(row=1, column=1, sticky="ew")
        self.bottom_text.bind("<KeyRelease>", lambda e: self._on_text_change())

        il.columnconfigure(1, weight=1)

        tk.Label(il,
                 text="※ Enter로 줄바꿈 가능  |  비워두면 해당 영역 미출력",
                 bg=CARD, font=("맑은 고딕", 8), fg="#94A3B8"
                 ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ── QR 미리보기 ──
        qf = self._card(main, "QR 코드 미리보기")
        qf.pack(fill="both", expand=True, pady=(0, 10))
        iq = tk.Frame(qf, bg=CARD, padx=10, pady=10)
        iq.pack()
        self.qr_label = tk.Label(iq, bg=CARD)
        self.qr_label.pack()

        uf = tk.Frame(qf, bg=CARD)
        uf.pack(fill="x", padx=10, pady=(0, 10))
        self.uid_var  = tk.StringVar(value="—")
        self.time_var = tk.StringVar(value="")
        tk.Label(uf, text="고유값:", bg=CARD,
                 font=("맑은 고딕", 9), fg="#64748B").pack(side="left")
        tk.Label(uf, textvariable=self.uid_var, bg=CARD,
                 font=("Consolas", 10, "bold"), fg="#1E293B").pack(side="left", padx=4)
        tk.Label(uf, textvariable=self.time_var, bg=CARD,
                 font=("맑은 고딕", 9), fg="#94A3B8").pack(side="right")

        # ── 버튼 ──
        bf = tk.Frame(main, bg=BG)
        bf.pack(fill="x")
        bst = dict(font=("맑은 고딕", 11, "bold"),
                   relief="flat", padx=20, pady=8, cursor="hand2")

        tk.Button(bf, text="⟳  새 QR 생성",
                  command=self._generate,
                  bg="#E2E8F0", fg="#1E293B", **bst
                  ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(bf, text="🖨  프린터로 출력",
                  command=self._print,
                  bg=ACCENT, fg="white",
                  activebackground="#1D4ED8", **bst
                  ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.status_var = tk.StringVar(value="준비")
        tk.Label(self, textvariable=self.status_var,
                 bg="#E2E8F0", fg="#475569",
                 font=("맑은 고딕", 9), anchor="w",
                 padx=10, pady=4
                 ).pack(fill="x", side="bottom")

    # ── 동작 ──────────────────────────────────────
    def _refresh_printers(self):
        printers = get_printers()
        self.printer_combo["values"] = printers
        if printers:
            default = ""
            if WIN32_AVAILABLE:
                try:
                    default = win32print.GetDefaultPrinter()
                except Exception:
                    pass
            self.printer_var.set(default if default in printers else printers[0])
        self._set_status(f"프린터 {len(printers)}개 감지됨")

    def _get_texts(self):
        return (self.top_text.get("1.0", "end-1c"),
                self.bottom_text.get("1.0", "end-1c"))

    def _load_saved_texts(self):
        cfg = load_config()
        top = cfg.get("top_text", "")
        bottom = cfg.get("bottom_text", "")
        orientation = cfg.get("orientation", "portrait")
        if top:
            self.top_text.insert("1.0", top)
        if bottom:
            self.bottom_text.insert("1.0", bottom)
        if orientation in ("portrait", "landscape"):
            self.orientation_var.set(orientation)

    def _save_texts(self):
        top, bottom = self._get_texts()
        save_config({
            "top_text": top,
            "bottom_text": bottom,
            "orientation": self.orientation_var.get(),
        })

    def _on_text_change(self):
        self._save_texts()
        if self._unique_value:
            self._update_preview()

    def _on_orientation_change(self):
        self._save_texts()
        if self._unique_value:
            self._update_preview()

    def _generate(self):
        self._unique_value, self._generated_at = generate_unique_value()
        self._update_preview()
        self.uid_var.set(self._unique_value)
        self.time_var.set(self._generated_at.strftime("%Y-%m-%d %H:%M:%S"))
        self._set_status(f"QR 생성 완료 → {self._unique_value}")

    def _update_preview(self):
        top, bottom = self._get_texts()
        qr_img = generate_qr_image(self._unique_value, box_size=6, border=3)
        full   = build_full_image(qr_img, self._unique_value, self._generated_at,
                                  top_text=top, bottom_text=bottom, scale=1.0)
        if self.orientation_var.get() == "landscape":
            full = full.rotate(-90, expand=True)

        max_w, max_h = 300, 420
        ratio   = min(max_w / full.width, max_h / full.height, 1.0)
        preview = full.resize((int(full.width * ratio), int(full.height * ratio)), Image.LANCZOS)

        self._tk_img = ImageTk.PhotoImage(preview)
        self.qr_label.config(image=self._tk_img)

    def _print(self):
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("프린터 없음", "출력할 프린터를 선택하세요.")
            return
        if not self._unique_value:
            messagebox.showwarning("QR 없음", "먼저 QR 코드를 생성하세요.")
            return

        top, bottom = self._get_texts()
        print_qr  = generate_qr_image(self._unique_value, box_size=20, border=6)
        print_img = build_full_image(print_qr, self._unique_value, self._generated_at,
                                     top_text=top, bottom_text=bottom, scale=3.0)
        if self.orientation_var.get() == "landscape":
            print_img = print_img.rotate(-90, expand=True)
        try:
            self._set_status(f"'{printer}' 로 출력 중...")
            self.update()
            print_image_win32(printer, print_img)
            self._set_status(f"✅ 출력 완료 → {printer}")
            messagebox.showinfo("출력 완료", f"QR 코드가 '{printer}' 로 전송되었습니다.")
        except RuntimeError as e:
            messagebox.showerror("오류", str(e))
            self._set_status("❌ 출력 실패")
        except Exception as e:
            messagebox.showerror("출력 오류", f"출력 중 오류가 발생했습니다\n{e}")
            self._set_status("❌ 출력 실패")

    def _set_status(self, msg: str):
        self.status_var.set(f"  {msg}")

    # ── 자동 업데이트 ─────────────────────────────
    def _check_update_background(self):
        """앱 시작 후 백그라운드에서 업데이트 확인."""
        def _worker():
            result = check_for_update()
            if result:
                self.after(0, lambda: self._show_update_dialog(result))
        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_dialog(self, info):
        """새 버전 알림 → 사용자 확인 → 다운로드 시작."""
        answer = messagebox.askyesno(
            "업데이트 알림",
            f"새 버전 v{info['version']}이 있습니다.\n"
            f"현재 버전: v{VERSION}\n\n"
            f"지금 업데이트하시겠습니까?",
        )
        if answer:
            self._perform_update(info)

    def _perform_update(self, info):
        """다운로드 진행률 표시 → 파일 교체 → 재시작."""
        url, name, expected_size = _find_asset_url(info["assets"])
        if not url:
            messagebox.showerror("업데이트 오류",
                                 "다운로드 가능한 파일을 찾을 수 없습니다.\n"
                                 f"직접 확인: {info['html_url']}")
            return

        # ── 프로그레스 다이얼로그 ──
        dlg = tk.Toplevel(self)
        dlg.title("업데이트 중...")
        dlg.resizable(False, False)
        dlg.configure(bg="#FFFFFF")
        if os.path.exists(self._icon_path):
            dlg.iconbitmap(self._icon_path)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        dw, dh = 340, 130
        x = self.winfo_x() + (self.winfo_width() - dw) // 2
        y = self.winfo_y() + (self.winfo_height() - dh) // 2
        dlg.geometry(f"{dw}x{dh}+{x}+{y}")

        tk.Label(dlg, text="업데이트 다운로드 중...",
                 font=("맑은 고딕", 10), bg="#FFFFFF"
                 ).pack(pady=(18, 8))
        bar = ttk.Progressbar(dlg, length=280, mode="determinate")
        bar.pack()
        pct_lbl = tk.Label(dlg, text="0 %",
                           font=("맑은 고딕", 9), bg="#FFFFFF", fg="#64748B")
        pct_lbl.pack(pady=(6, 0))

        ext = ".exe" if getattr(sys, "frozen", False) else ".py"
        # 같은 디렉토리에 다운로드 → move가 원자적 rename이 되도록 함
        current_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        dest = os.path.join(current_dir, f"QR-Code-Printer-update{ext}")
        try:
            test_path = os.path.join(current_dir, ".update_test")
            with open(test_path, "w") as tf:
                tf.write("test")
            os.unlink(test_path)
        except OSError:
            dest = os.path.join(tempfile.gettempdir(), f"QR-Code-Printer-update{ext}")

        def _on_progress(downloaded, total):
            pct = int(downloaded / total * 100)
            self.after(0, lambda p=pct: (
                bar.configure(value=p),
                pct_lbl.configure(text=f"{p} %"),
            ))

        def _download():
            try:
                download_file(url, dest, _on_progress, expected_size)
                self.after(0, lambda: _done(dlg))
            except Exception as e:
                self.after(0, lambda: _error(dlg, str(e)))

        def _done(d):
            d.destroy()
            if messagebox.askyesno("업데이트 준비 완료",
                                   "다운로드가 완료되었습니다.\n"
                                   "앱을 재시작하여 업데이트를 적용합니다."):
                apply_update(dest)
            else:
                # 거부 시 임시 파일 정리
                try:
                    os.unlink(dest)
                except OSError:
                    pass

        def _error(d, msg):
            d.destroy()
            messagebox.showerror("다운로드 오류",
                                 f"업데이트 다운로드에 실패했습니다.\n{msg}")

        threading.Thread(target=_download, daemon=True).start()


# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = QRPrinterApp()
    app.mainloop()
