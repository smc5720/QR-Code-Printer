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
import time
import threading
import subprocess
import urllib.request
import urllib.error
import urllib.parse

VERSION = "1.9.0"
GITHUB_REPO = "smc5720/QR-Code-Printer"

API_BASE_URL = "https://kfrental.com"
API_KEY = ""  # GitHub Actions 빌드 시 주입
API_MAX_RETRIES = 5

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
# 각 패밀리별 (regular, bold) 경로
FONT_FAMILIES = {
    "맑은 고딕":     ("C:/Windows/Fonts/malgun.ttf",  "C:/Windows/Fonts/malgunbd.ttf"),
    "Arial":        ("C:/Windows/Fonts/arial.ttf",   "C:/Windows/Fonts/arialbd.ttf"),
    "Consolas":     ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/consolab.ttf"),
    "Courier New":  ("C:/Windows/Fonts/cour.ttf",    "C:/Windows/Fonts/courbd.ttf"),
}
DEFAULT_FONT_FAMILY = "맑은 고딕"


def load_font(size: int, family: str = DEFAULT_FONT_FAMILY, bold: bool = False):
    """지정한 패밀리/굵기의 폰트를 로드. 없으면 다른 패밀리로 폴백."""
    primary = FONT_FAMILIES.get(family, FONT_FAMILIES[DEFAULT_FONT_FAMILY])
    # 1) 요청한 패밀리 (bold 우선)
    candidates = [primary[1 if bold else 0], primary[0]]
    # 2) 다른 패밀리 폴백
    for f, paths in FONT_FAMILIES.items():
        if f == family:
            continue
        candidates.append(paths[1 if bold else 0])
        candidates.append(paths[0])
    for fp in candidates:
        if fp and os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ──────────────────────────────────────────────
#  핵심 로직
# ──────────────────────────────────────────────

_BASE36_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def generate_unique_value():
    """현재 시간(epoch μs) 기반 고유값을 대문자 Base36으로 인코딩. 최소 10자 보장."""
    now = datetime.datetime.now()
    n = int(now.timestamp() * 1_000_000)
    out = []
    while n > 0:
        n, r = divmod(n, 36)
        out.append(_BASE36_ALPHABET[r])
    # 2085년까지 자연스럽게 10자, 이후 11자. zfill로 초기값·이상 시계 상황에도 10자 하한 보장.
    return "".join(reversed(out)).zfill(10), now


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
    caption_family: str = DEFAULT_FONT_FAMILY,
    caption_size: int = 17,
    caption_bold: bool = False,
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
    fs_caption = max(8,  int(caption_size * scale))
    pad_v      = max(6,  int(8  * scale))
    line_gap   = 4

    font_info    = load_font(fs_info)
    font_caption = load_font(fs_caption, caption_family, caption_bold)

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


def print_image_win32(printer_name: str, img: Image.Image, copies: int = 1):
    if not WIN32_AVAILABLE:
        raise RuntimeError("pywin32가 설치되어 있지 않습니다.\npip install pywin32 를 실행하세요.")

    copies = max(1, int(copies))

    with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as tmp:
        tmp_path = tmp.name
    img.save(tmp_path, "BMP")

    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            hdc.StartDoc("QR Code")

            px = hdc.GetDeviceCaps(win32con.HORZRES)
            py = hdc.GetDeviceCaps(win32con.VERTRES)

            iw, ih = img.size
            s = min(px / iw, py / ih) * 0.85
            dw, dh = int(iw * s), int(ih * s)
            xo = (px - dw) // 2
            yo = int(py * 0.05)

            dib = ImageWin.Dib(img)
            for _ in range(copies):
                hdc.StartPage()
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
#  API 클라이언트
# ──────────────────────────────────────────────

class DuplicateCodeError(Exception):
    """서버에서 중복 코드 응답 (409 PENDING_CODE_ALREADY_EXISTS)."""
    pass


class InvalidApiKeyError(Exception):
    """API 키 인증 실패 (401 INVALID_API_KEY)."""
    pass


def _resolve_api_key() -> str:
    """API 키 우선순위: 소스 상수 → 설정 파일 → 환경 변수. 없으면 빈 문자열."""
    if API_KEY:
        return API_KEY
    cfg = load_config()
    key = cfg.get("api_key", "")
    if key:
        return key
    return os.environ.get("QR_PRINTER_API_KEY", "")


def api_check_code(product_code: str, api_key: str) -> dict:
    """
    GET /api/stocks/pending/check — 코드 중복 확인.
    반환: {"exists": bool, "location": str|None}
    """
    url = f"{API_BASE_URL}/api/stocks/pending/check?productCode={product_code}"
    req = urllib.request.Request(url, headers={
        "X-API-Key": api_key,
        "User-Agent": "QR-Code-Printer",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise InvalidApiKeyError("API 키가 유효하지 않습니다.")
        raise


def api_search_codes(query: str, api_key: str) -> list:
    """
    GET /api/stocks/pending/search?q={query} — 코드 prefix 검색.
    반환: items 리스트 [{id, productCode, status, createdAt, registeredAt}]
    """
    url = f"{API_BASE_URL}/api/stocks/pending/search?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={
        "X-API-Key": api_key,
        "User-Agent": "QR-Code-Printer",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", [])
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise InvalidApiKeyError("API 키가 유효하지 않습니다.")
        raise


def api_register_code(product_code: str, api_key: str) -> dict:
    """
    POST /api/stocks/pending — 대기열 등록.
    201 → 성공 dict, 409 → DuplicateCodeError.
    """
    url = f"{API_BASE_URL}/api/stocks/pending"
    body = json.dumps({"productCode": product_code}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "QR-Code-Printer",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise InvalidApiKeyError("API 키가 유효하지 않습니다.")
        if e.code == 409:
            raise DuplicateCodeError("이미 대기열에 등록된 상품 코드입니다.")
        raise


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

        # 출력 상태 추적 (상품 전환 시 QR 재사용 방지용)
        self._print_count   = 0       # 현재 QR이 몇 매 출력되었는지
        self._last_print_at = None    # 마지막 출력 시각 (datetime)
        self._print_history = []      # [{id, count, at}] · 최신이 앞, 최대 20건 (세션 내)

        self._build_ui()
        self._load_saved_texts()
        self._refresh_printers()
        self._generate()
        # 가로 600px 고정, 세로는 컨텐츠에 맞춰 자동 조절
        self._refit_height()
        self.after(1000, self._check_update_background)
        self.after(30_000, self._refresh_warn_label)

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
        io = tk.Frame(pf, bg=CARD, padx=10)
        io.pack(fill="x", pady=(0, 8))
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

        tk.Label(io, text="수량",
                 bg=CARD, font=("맑은 고딕", 9, "bold"), fg="#475569"
                 ).pack(side="left", padx=(20, 0))
        self.quantity_var = tk.StringVar(value="1")
        tk.Spinbox(io, from_=1, to=999, textvariable=self.quantity_var,
                   width=6, font=("맑은 고딕", 10), justify="center",
                   relief="solid", bd=1
                   ).pack(side="left", padx=(8, 0))
        tk.Label(io, text="매",
                 bg=CARD, font=("맑은 고딕", 9), fg="#64748B"
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

        # 폰트 옵션 (문구에 적용)
        ff = tk.Frame(il, bg=CARD)
        ff.pack(fill="x", pady=(0, 8))
        tk.Label(ff, text="폰트",
                 bg=CARD, font=("맑은 고딕", 9, "bold"),
                 fg="#475569", width=8, anchor="nw"
                 ).pack(side="left")
        self.font_family_var = tk.StringVar(value=DEFAULT_FONT_FAMILY)
        font_combo = ttk.Combobox(ff, textvariable=self.font_family_var,
                                  values=list(FONT_FAMILIES.keys()),
                                  state="readonly", width=12,
                                  font=("맑은 고딕", 9))
        font_combo.pack(side="left")
        font_combo.bind("<<ComboboxSelected>>", lambda e: self._on_font_change())

        tk.Label(ff, text="크기",
                 bg=CARD, font=("맑은 고딕", 9, "bold"), fg="#475569"
                 ).pack(side="left", padx=(12, 4))
        self.font_size_var = tk.StringVar(value="17")
        size_combo = ttk.Combobox(ff, textvariable=self.font_size_var,
                                  values=["10", "12", "14", "16", "17",
                                          "18", "20", "24", "28", "32"],
                                  state="readonly", width=5,
                                  font=("맑은 고딕", 9))
        size_combo.pack(side="left")
        size_combo.bind("<<ComboboxSelected>>", lambda e: self._on_font_change())

        self.font_bold_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ff, text="굵게", variable=self.font_bold_var,
                       command=self._on_font_change,
                       bg=CARD, font=("맑은 고딕", 9), cursor="hand2"
                       ).pack(side="left", padx=(12, 0))

        # 텍스트 입력
        tg = tk.Frame(il, bg=CARD)
        tg.pack(fill="x")

        tk.Label(tg, text="상단 문구", **label_style).grid(row=0, column=0, sticky="nw", pady=(0, 6))
        self.top_text = tk.Text(tg, **text_style)
        self.top_text.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        self.top_text.bind("<KeyRelease>", lambda e: self._on_text_change())

        tk.Label(tg, text="하단 문구", **label_style).grid(row=1, column=0, sticky="nw")
        self.bottom_text = tk.Text(tg, **text_style)
        self.bottom_text.grid(row=1, column=1, sticky="ew")
        self.bottom_text.bind("<KeyRelease>", lambda e: self._on_text_change())

        tg.columnconfigure(1, weight=1)

        tk.Label(tg,
                 text="※ Enter로 줄바꿈 가능  |  비워두면 해당 영역 미출력",
                 bg=CARD, font=("맑은 고딕", 8), fg="#94A3B8"
                 ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ── QR 미리보기 ──
        qf = self._card(main, "QR 코드 미리보기")
        qf.pack(fill="both", expand=True, pady=(0, 10))

        # 경고 배너 (출력 후 표시) — 상품 전환 시 실수 방지
        self.warn_var = tk.StringVar(value="")
        self.warn_label = tk.Label(qf, textvariable=self.warn_var,
                                   bg="#FEF3C7", fg="#92400E",
                                   font=("맑은 고딕", 9, "bold"),
                                   anchor="w", padx=10, pady=6)
        # 초기에는 숨김 (출력 후 _apply_print_state에서 pack)

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
        self.history_btn = tk.Button(uf, text="이력 보기",
                                     command=self._show_history,
                                     bg="#E2E8F0", fg="#1E293B",
                                     font=("맑은 고딕", 8), relief="flat",
                                     padx=6, cursor="hand2",
                                     state="disabled")
        self.history_btn.pack(side="right", padx=(6, 0))
        tk.Label(uf, textvariable=self.time_var, bg=CARD,
                 font=("맑은 고딕", 9), fg="#94A3B8").pack(side="right")

        # ── 버튼 ──
        bf = tk.Frame(main, bg=BG)
        bf.pack(fill="x")
        bst = dict(font=("맑은 고딕", 11, "bold"),
                   relief="flat", padx=20, pady=8, cursor="hand2")

        self._accent_color = ACCENT
        self.generate_btn = tk.Button(bf, text="⟳  새 QR 생성",
                                      command=self._generate,
                                      bg="#E2E8F0", fg="#1E293B", **bst)
        self.generate_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.print_btn = tk.Button(bf, text="🖨  프린터로 출력",
                                   command=self._print,
                                   bg=ACCENT, fg="white",
                                   activebackground="#1D4ED8", **bst)
        self.print_btn.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self.search_btn = tk.Button(bf, text="🔍  서버 검색",
                                    command=self._show_server_search,
                                    bg="#10B981", fg="white",
                                    activebackground="#059669", **bst)
        self.search_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

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
        family = cfg.get("font_family", DEFAULT_FONT_FAMILY)
        if family in FONT_FAMILIES:
            self.font_family_var.set(family)
        size = cfg.get("font_size", 17)
        self.font_size_var.set(str(size))
        self.font_bold_var.set(bool(cfg.get("font_bold", False)))
        # 출력 이력 (세션 간 영속)
        self._print_history = []
        for h in cfg.get("print_history", []):
            try:
                self._print_history.append({
                    "id": str(h["id"]),
                    "count": int(h["count"]),
                    "at": datetime.datetime.fromisoformat(h["at"]),
                })
            except (KeyError, TypeError, ValueError):
                continue  # 손상된 엔트리는 조용히 스킵
        del self._print_history[20:]

    def _save_texts(self):
        top, bottom = self._get_texts()
        save_config({
            "top_text": top,
            "bottom_text": bottom,
            "orientation": self.orientation_var.get(),
            "font_family": self.font_family_var.get(),
            "font_size": self._get_font_size(),
            "font_bold": self.font_bold_var.get(),
            "print_history": [
                {"id": h["id"], "count": h["count"], "at": h["at"].isoformat()}
                for h in self._print_history
            ],
        })

    def _get_font_size(self) -> int:
        try:
            return max(6, int(self.font_size_var.get()))
        except (TypeError, ValueError):
            return 17

    def _on_text_change(self):
        self._save_texts()
        if self._unique_value:
            self._update_preview()

    def _on_orientation_change(self):
        self._save_texts()
        if self._unique_value:
            self._update_preview()

    def _on_font_change(self):
        self._save_texts()
        if self._unique_value:
            self._update_preview()

    def _generate(self):
        self._unique_value, self._generated_at = generate_unique_value()
        # 새 QR은 아직 출력되지 않은 상태 → 경고/버튼 원복
        self._print_count   = 0
        self._last_print_at = None
        self.quantity_var.set("1")
        self._update_preview()
        self.uid_var.set(self._unique_value)
        self.time_var.set(self._generated_at.strftime("%Y-%m-%d %H:%M:%S"))
        self._apply_print_state()
        self._set_status(f"QR 생성 완료 → {self._unique_value}")

    def _update_preview(self):
        top, bottom = self._get_texts()
        qr_img = generate_qr_image(self._unique_value, box_size=6, border=3)
        full   = build_full_image(qr_img, self._unique_value, self._generated_at,
                                  top_text=top, bottom_text=bottom, scale=1.0,
                                  caption_family=self.font_family_var.get(),
                                  caption_size=self._get_font_size(),
                                  caption_bold=self.font_bold_var.get())
        if self.orientation_var.get() == "landscape":
            full = full.rotate(-90, expand=True)

        max_w, max_h = 300, 420
        ratio   = min(max_w / full.width, max_h / full.height, 1.0)
        preview = full.resize((int(full.width * ratio), int(full.height * ratio)), Image.LANCZOS)

        self._tk_img = ImageTk.PhotoImage(preview)
        self.qr_label.config(image=self._tk_img)
        self._refit_height()

    def _print(self):
        if not self._unique_value:
            messagebox.showwarning("QR 없음", "먼저 QR 코드를 생성하세요.")
            return

        copies = self._read_copies()

        # 이미 출력된 QR을 다시 출력하려 하면 확인 — 상품 전환 시 실수 방지
        if self._print_count > 0:
            elapsed = self._format_elapsed(self._last_print_at)
            answer = messagebox.askyesno(
                "중복 출력 확인",
                f"이 QR은 {elapsed}에 {self._print_count}매 출력되었습니다.\n\n"
                f"같은 상품에 추가로 붙이시나요?\n"
                f"다른 상품이면 '취소' 후 '새 QR 생성'을 눌러주세요.",
                icon="warning", default="no")
            if not answer:
                self._set_status("출력 취소됨")
                return
            self._execute_print_and_update(self._unique_value, copies)
            return

        # 최초 출력: API 연동
        api_key = _resolve_api_key()
        if api_key:
            self._print_with_api_check(copies, api_key)
        else:
            self._execute_print_and_update(self._unique_value, copies)

    def _execute_print_and_update(self, uid: str, copies: int):
        """_do_print 실행 후 상태·이력·UI 갱신. API 성공 콜백과 직접 출력 경로에서 공유."""
        printer = self._do_print(uid, copies)
        if printer is None:
            return
        self._print_count  += copies
        self._last_print_at = datetime.datetime.now()
        self._push_history(uid, self._print_count, self._last_print_at)
        self._apply_print_state()
        self._set_status(f"✅ 출력 완료 → {printer} ({copies}매 · 누적 {self._print_count}매)")
        messagebox.showinfo("출력 완료",
                            f"QR 코드가 '{printer}' 로 {copies}매 전송되었습니다.\n"
                            f"(이 QR 누적 {self._print_count}매)")

    def _print_with_api_check(self, copies: int, api_key: str):
        """코드 중복 확인 → 대기열 등록 → 출력. 모달 진행 다이얼로그에서 실행."""
        dlg = tk.Toplevel(self)
        dlg.title("QR 등록 중...")
        dlg.resizable(False, False)
        dlg.configure(bg="#FFFFFF")
        if os.path.exists(self._icon_path):
            try:
                dlg.iconbitmap(self._icon_path)
            except Exception:
                pass
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        dw, dh = 340, 130
        x = self.winfo_x() + (self.winfo_width() - dw) // 2
        y = self.winfo_y() + (self.winfo_height() - dh) // 2
        dlg.geometry(f"{dw}x{dh}+{x}+{y}")

        step_var = tk.StringVar(value="코드 확인 중...")
        tk.Label(dlg, textvariable=step_var,
                 font=("맑은 고딕", 10), bg="#FFFFFF").pack(pady=(18, 4))
        retry_var = tk.StringVar(value="")
        tk.Label(dlg, textvariable=retry_var,
                 font=("맑은 고딕", 9), bg="#FFFFFF", fg="#64748B").pack(pady=(0, 8))
        bar = ttk.Progressbar(dlg, length=280, mode="indeterminate")
        bar.pack()
        bar.start(15)

        def _update_code(code, generated_at):
            self._unique_value = code
            self._generated_at = generated_at
            self._print_count = 0
            self._last_print_at = None
            self.uid_var.set(code)
            self.time_var.set(generated_at.strftime("%Y-%m-%d %H:%M:%S"))
            self._update_preview()

        def _on_api_success(code, cps):
            dlg.destroy()
            self._execute_print_and_update(code, cps)

        def _on_network_error(error_msg, cps):
            dlg.destroy()
            answer = messagebox.askyesno(
                "서버 연결 오류",
                f"서버에 연결할 수 없습니다.\n\n"
                f"오류: {error_msg}\n\n"
                f"등록 없이 출력하시겠습니까?\n"
                f"(나중에 수동 등록이 필요할 수 있습니다)",
                icon="warning")
            if answer:
                self._execute_print_and_update(self._unique_value, cps)
            else:
                self._set_status("출력 취소됨")

        def _on_invalid_api_key(cps):
            dlg.destroy()
            answer = messagebox.askyesno(
                "API 키 오류",
                "API 키가 유효하지 않습니다.\n\n"
                "등록 없이 출력하시겠습니까?\n"
                "(나중에 수동 등록이 필요할 수 있습니다)",
                icon="warning")
            if answer:
                self._execute_print_and_update(self._unique_value, cps)
            else:
                self._set_status("출력 취소됨")

        def _on_max_retries():
            dlg.destroy()
            messagebox.showerror(
                "코드 생성 실패",
                f"코드가 {API_MAX_RETRIES}회 연속 중복되었습니다.\n"
                f"잠시 후 다시 시도해 주세요.")
            self._set_status("❌ 코드 중복 초과")

        def _worker():
            current_code = self._unique_value

            for attempt in range(1, API_MAX_RETRIES + 1):
                if attempt > 1:
                    self.after(0, lambda a=attempt: (
                        step_var.set("코드 확인 중..."),
                        retry_var.set(f"코드 중복 — 새 코드로 재시도 ({a}/{API_MAX_RETRIES})"),
                    ))

                # 1) 중복 확인
                try:
                    result = api_check_code(current_code, api_key)
                except InvalidApiKeyError:
                    self.after(0, lambda: _on_invalid_api_key(copies))
                    return
                except Exception as e:
                    self.after(0, lambda msg=str(e): _on_network_error(msg, copies))
                    return

                if result.get("exists"):
                    current_code, gen_at = generate_unique_value()
                    self.after(0, lambda c=current_code, t=gen_at: _update_code(c, t))
                    continue

                self.after(0, lambda: step_var.set("✓ 코드 중복 확인 완료"))
                time.sleep(0.5)

                # 2) 대기열 등록
                self.after(0, lambda: step_var.set("대기열 등록 중..."))
                try:
                    api_register_code(current_code, api_key)
                except InvalidApiKeyError:
                    self.after(0, lambda: _on_invalid_api_key(copies))
                    return
                except DuplicateCodeError:
                    current_code, gen_at = generate_unique_value()
                    self.after(0, lambda c=current_code, t=gen_at: _update_code(c, t))
                    continue
                except Exception as e:
                    self.after(0, lambda msg=str(e): _on_network_error(msg, copies))
                    return

                self.after(0, lambda: step_var.set("✓ 대기열 등록 완료"))
                time.sleep(0.5)

                # 성공
                self.after(0, lambda c=current_code: _on_api_success(c, copies))
                return

            # 재시도 초과
            self.after(0, _on_max_retries)

        threading.Thread(target=_worker, daemon=True).start()

    def _read_copies(self) -> int:
        try:
            return max(1, int(self.quantity_var.get()))
        except (TypeError, ValueError):
            return 1

    def _do_print(self, uid: str, copies: int):
        """
        지정한 uid로 실제 인쇄 작업 수행. 성공 시 printer 이름 반환, 실패 시 None.
        호출자가 카운터/이력/UI 상태를 갱신하도록 책임 분리.
        """
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("프린터 없음", "출력할 프린터를 선택하세요.")
            return None

        top, bottom = self._get_texts()
        print_qr  = generate_qr_image(uid, box_size=20, border=6)
        print_img = build_full_image(print_qr, uid, datetime.datetime.now(),
                                     top_text=top, bottom_text=bottom, scale=3.0,
                                     caption_family=self.font_family_var.get(),
                                     caption_size=self._get_font_size(),
                                     caption_bold=self.font_bold_var.get())
        if self.orientation_var.get() == "landscape":
            print_img = print_img.rotate(-90, expand=True)
        try:
            self._set_status(f"'{printer}' 로 {copies}매 출력 중...")
            self.update()
            print_image_win32(printer, print_img, copies=copies)
            return printer
        except RuntimeError as e:
            messagebox.showerror("오류", str(e))
            self._set_status("❌ 출력 실패")
            return None
        except Exception as e:
            messagebox.showerror("출력 오류", f"출력 중 오류가 발생했습니다\n{e}")
            self._set_status("❌ 출력 실패")
            return None

    def _set_status(self, msg: str):
        self.status_var.set(f"  {msg}")

    # ── 출력 상태/이력 ────────────────────────────
    @staticmethod
    def _format_elapsed(t) -> str:
        """datetime → '방금 전' / 'N분 전' / 'N시간 전'."""
        if t is None:
            return "방금 전"
        sec = int((datetime.datetime.now() - t).total_seconds())
        if sec < 60:
            return "방금 전"
        if sec < 3600:
            return f"{sec // 60}분 전"
        return f"{sec // 3600}시간 전"

    def _push_history(self, uid: str, count: int, at):
        """출력 이력에 추가. 같은 ID가 있으면 업데이트. 최대 20건 유지. 디스크에 영속화."""
        self._print_history = [h for h in self._print_history if h["id"] != uid]
        self._print_history.insert(0, {"id": uid, "count": count, "at": at})
        del self._print_history[20:]
        self._save_texts()

    def _apply_print_state(self):
        """현재 _print_count에 맞춰 배너/버튼 상태 전환."""
        has_print = self._print_count > 0
        if has_print:
            self._refresh_warn_label(schedule_next=False)
            self.warn_label.pack(fill="x", padx=10, pady=(8, 0), before=self.qr_label.master)
            # 출력 버튼 → 회색 '추가 출력'
            self.print_btn.config(text="🖨  추가 출력",
                                  bg="#E2E8F0", fg="#1E293B",
                                  activebackground="#CBD5E1")
            # 새 QR 버튼 → 파란색 강조
            self.generate_btn.config(text="⟳  새 QR 생성",
                                     bg=self._accent_color, fg="white",
                                     activebackground="#1D4ED8")
        else:
            self.warn_label.pack_forget()
            self.print_btn.config(text="🖨  프린터로 출력",
                                  bg=self._accent_color, fg="white",
                                  activebackground="#1D4ED8")
            self.generate_btn.config(text="⟳  새 QR 생성",
                                     bg="#E2E8F0", fg="#1E293B",
                                     activebackground="#CBD5E1")
        self.history_btn.config(state=("normal" if self._print_history else "disabled"))
        self._refit_height()

    def _refit_height(self):
        """가로 600 유지, 세로는 현재 요구 높이로 재조정. 배너/방향 변경 등 레이아웃 변화 후 호출."""
        # PhotoImage 스왑 등 이미지 기반 reqheight 갱신을 확실히 반영하기 위해 full update
        self.update()
        self.geometry(f"600x{self.winfo_reqheight()}")

    def _refresh_warn_label(self, schedule_next: bool = True):
        """배너의 '~분 전' 표시 주기적 갱신."""
        if self._print_count > 0 and self._last_print_at is not None:
            self.warn_var.set(
                f"⚠ 이 QR은 이미 {self._print_count}매 출력됨 · "
                f"{self._format_elapsed(self._last_print_at)}  —  "
                f"다른 상품이면 반드시 '새 QR 생성'을 누르세요")
        if schedule_next:
            self.after(30_000, self._refresh_warn_label)

    def _show_history(self):
        """최근 출력 이력 팝업 (최대 20건). 선택 후 재출력 가능."""
        if not self._print_history:
            return
        win = tk.Toplevel(self)
        win.title("최근 출력 이력")
        win.configure(bg="#F0F4F8")
        win.transient(self)
        if os.path.exists(self._icon_path):
            try:
                win.iconbitmap(self._icon_path)
            except Exception:
                pass

        tk.Label(win, text="최근 출력 이력  (최대 20건 · 영구 저장)",
                 bg="#F0F4F8", fg="#1E293B",
                 font=("맑은 고딕", 10, "bold"),
                 padx=12, pady=8).pack(fill="x")

        tk.Label(win,
                 text="※ 행을 선택하고 '재출력'을 누르면 현재 수량으로 다시 출력합니다. (더블클릭도 가능)",
                 bg="#F0F4F8", fg="#64748B",
                 font=("맑은 고딕", 8),
                 padx=12).pack(fill="x", pady=(0, 4))

        frame = tk.Frame(win, bg="#F0F4F8")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        tree = ttk.Treeview(frame, columns=("id", "count", "at"),
                            show="headings", height=min(20, len(self._print_history)))
        tree.heading("id", text="ID")
        tree.heading("count", text="매수")
        tree.heading("at", text="마지막 출력")
        tree.column("id", width=200, anchor="w")
        tree.column("count", width=60, anchor="center")
        tree.column("at", width=150, anchor="center")
        tree.pack(fill="both", expand=True)

        self._populate_history_tree(tree)

        # 행 iid를 uid로 지정했으므로 선택값 = uid
        def do_reprint(_event=None):
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("선택 없음", "재출력할 이력을 먼저 선택하세요.", parent=win)
                return
            uid = sel[0]
            self._reprint_from_history(uid, tree=tree, parent=win)

        tree.bind("<Double-1>", do_reprint)

        btns = tk.Frame(win, bg="#F0F4F8")
        btns.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(btns, text="🖨  재출력",
                  command=do_reprint,
                  bg=self._accent_color, fg="white",
                  font=("맑은 고딕", 9, "bold"),
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  activebackground="#1D4ED8"
                  ).pack(side="left")
        tk.Button(btns, text="닫기", command=win.destroy,
                  bg="#E2E8F0", fg="#1E293B",
                  font=("맑은 고딕", 9), relief="flat",
                  padx=12, pady=5, cursor="hand2"
                  ).pack(side="right")

    def _populate_history_tree(self, tree):
        """Treeview를 현재 _print_history 로 채움. iid=uid."""
        for iid in tree.get_children():
            tree.delete(iid)
        for h in self._print_history:
            tree.insert("", "end", iid=h["id"], values=(
                h["id"], f"{h['count']}매",
                h["at"].strftime("%Y-%m-%d %H:%M:%S"),
            ))

    def _reprint_from_history(self, uid: str, tree=None, parent=None):
        """과거 이력의 QR을 현재 수량으로 재출력."""
        entry = next((h for h in self._print_history if h["id"] == uid), None)
        if entry is None:
            return
        copies = self._read_copies()
        elapsed = self._format_elapsed(entry["at"])
        answer = messagebox.askyesno(
            "과거 QR 재출력",
            f"선택한 과거 QR을 추가로 {copies}매 출력합니다.\n\n"
            f"ID: {uid}\n"
            f"기존 누적: {entry['count']}매 ({elapsed})\n\n"
            f"계속하시겠습니까?",
            icon="warning", default="no", parent=parent)
        if not answer:
            return

        printer = self._do_print(uid, copies)
        if printer is None:
            return

        new_count = entry["count"] + copies
        now = datetime.datetime.now()
        self._push_history(uid, new_count, now)

        # 재출력한 ID가 현재 화면의 QR이면 메인 UI 상태도 동기화
        if uid == self._unique_value:
            self._print_count   = new_count
            self._last_print_at = now
            self._apply_print_state()
        else:
            # 이력 버튼 활성 유지 (이력 비어있지 않음)
            self.history_btn.config(state="normal")

        if tree is not None and tree.winfo_exists():
            self._populate_history_tree(tree)

        self._set_status(f"✅ 과거 QR 재출력 → {printer} ({copies}매)")
        messagebox.showinfo("재출력 완료",
                            f"과거 QR을 {copies}매 재출력했습니다.\n"
                            f"ID: {uid}\n"
                            f"해당 QR 누적: {new_count}매",
                            parent=parent)

    # ── 서버 검색 재출력 ──────────────────────────
    def _show_server_search(self):
        """서버에서 코드를 prefix 검색하여 재출력하는 모달 다이얼로그."""
        api_key = _resolve_api_key()
        if not api_key:
            messagebox.showerror(
                "API 키 없음",
                "서버 검색을 사용하려면 API 키가 필요합니다.\n"
                "설정 파일의 'api_key' 항목을 확인하세요.")
            return

        win = tk.Toplevel(self)
        win.title("서버 코드 검색 재출력")
        win.configure(bg="#F0F4F8")
        win.transient(self)
        win.grab_set()
        if os.path.exists(self._icon_path):
            try:
                win.iconbitmap(self._icon_path)
            except Exception:
                pass

        tk.Label(win, text="서버에서 코드를 검색하여 재출력합니다",
                 bg="#F0F4F8", fg="#1E293B",
                 font=("맑은 고딕", 10, "bold"),
                 padx=12, pady=8).pack(fill="x")
        tk.Label(win,
                 text="※ 3자 이상 입력하면 자동 검색됩니다. 결과를 선택 후 '재출력'을 누르세요.",
                 bg="#F0F4F8", fg="#64748B",
                 font=("맑은 고딕", 8), padx=12).pack(fill="x", pady=(0, 6))

        sf = tk.Frame(win, bg="#F0F4F8", padx=12)
        sf.pack(fill="x", pady=(0, 6))
        tk.Label(sf, text="코드 일부 입력 (최대 10자):",
                 bg="#F0F4F8", fg="#475569",
                 font=("맑은 고딕", 9)).pack(anchor="w")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(sf, textvariable=search_var,
                                 font=("Consolas", 11))
        search_entry.pack(fill="x", pady=(4, 0))

        result_label_var = tk.StringVar(value="검색 결과")
        tk.Label(win, textvariable=result_label_var,
                 bg="#F0F4F8", fg="#1E293B",
                 font=("맑은 고딕", 9, "bold"),
                 padx=12).pack(fill="x", anchor="w")

        tf = tk.Frame(win, bg="#F0F4F8")
        tf.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        tree = ttk.Treeview(tf, columns=("code", "status", "created"),
                            show="headings", height=10)
        tree.heading("code", text="코드")
        tree.heading("status", text="상태")
        tree.heading("created", text="생성일")
        tree.column("code", width=160, anchor="w")
        tree.column("status", width=80, anchor="center")
        tree.column("created", width=150, anchor="center")
        tree.tag_configure("pending", foreground="#DC2626")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        notice_var = tk.StringVar(value="")
        notice_lbl = tk.Label(win, textvariable=notice_var,
                              bg="#FEF3C7", fg="#92400E",
                              font=("맑은 고딕", 8), padx=12, pady=4)

        btns = tk.Frame(win, bg="#F0F4F8")
        btns.pack(fill="x", padx=12, pady=(8, 10))
        reprint_btn = tk.Button(btns, text="🖨  재출력",
                                bg=self._accent_color, fg="white",
                                font=("맑은 고딕", 9, "bold"),
                                relief="flat", padx=14, pady=5, cursor="hand2",
                                activebackground="#1D4ED8", state="disabled")
        reprint_btn.pack(side="left")
        tk.Button(btns, text="닫기", command=win.destroy,
                  bg="#E2E8F0", fg="#1E293B",
                  font=("맑은 고딕", 9), relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(side="right")

        _after_id = [None]

        def _update_tree(items):
            for iid in tree.get_children():
                tree.delete(iid)
            for item in items:
                code = item["productCode"]
                is_pending = item.get("status") == "PENDING"
                status_text = "미등록" if is_pending else "등록완료"
                raw_dt = item.get("createdAt", "") or ""
                created = raw_dt[:16].replace("T", " ") if raw_dt else ""
                tag = "pending" if is_pending else ""
                tree.insert("", "end", iid=code,
                            values=(code, status_text, created), tags=(tag,))
            cnt = len(items)
            result_label_var.set(f"검색 결과  {cnt}건")
            if cnt >= 20:
                notice_var.set("⚠  최대 20건 표시 중 — 더 구체적인 코드를 입력하세요")
                notice_lbl.pack(fill="x", padx=0, pady=(4, 0))
            else:
                notice_lbl.pack_forget()
            reprint_btn.config(state="disabled")

        def _do_search(query):
            if not win.winfo_exists():
                return
            result_label_var.set("검색 중…")

            def _worker():
                try:
                    items = api_search_codes(query, api_key)
                    if win.winfo_exists():
                        win.after(0, lambda: _update_tree(items))
                except InvalidApiKeyError:
                    if win.winfo_exists():
                        win.after(0, lambda: (
                            result_label_var.set("오류: API 키 인증 실패"),
                            messagebox.showerror("API 키 오류",
                                                 "API 키가 유효하지 않습니다.",
                                                 parent=win),
                        ))
                except Exception as exc:
                    if win.winfo_exists():
                        win.after(0, lambda e=exc: result_label_var.set(f"오류: {e}"))

            threading.Thread(target=_worker, daemon=True).start()

        def _on_key_change(*_):
            if _after_id[0] is not None:
                win.after_cancel(_after_id[0])
                _after_id[0] = None
            query = search_var.get().strip()
            if len(query) >= 3:
                _after_id[0] = win.after(300, lambda q=query: _do_search(q))
            elif not query:
                _update_tree([])
                result_label_var.set("검색 결과")

        search_var.trace_add("write", _on_key_change)

        def _on_select(_event=None):
            reprint_btn.config(state="normal" if tree.selection() else "disabled")

        def _on_reprint(_event=None):
            sel = tree.selection()
            if not sel:
                return
            uid = sel[0]
            self._reprint_from_search(uid, parent=win)

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<Double-1>", _on_reprint)
        reprint_btn.config(command=_on_reprint)

        dw, dh = 440, 460
        x = self.winfo_x() + (self.winfo_width() - dw) // 2
        y = self.winfo_y() + (self.winfo_height() - dh) // 2
        win.geometry(f"{dw}x{dh}+{x}+{y}")
        search_entry.focus_set()

    def _reprint_from_search(self, uid: str, parent=None):
        """서버 검색으로 찾은 코드를 현재 수량으로 재출력하고 이력에 추가."""
        copies = self._read_copies()
        answer = messagebox.askyesno(
            "서버 검색 재출력",
            f"검색된 코드를 {copies}매 출력합니다.\n\n"
            f"코드: {uid}\n\n"
            f"계속하시겠습니까?",
            icon="question", default="yes", parent=parent)
        if not answer:
            return

        printer = self._do_print(uid, copies)
        if printer is None:
            return

        existing = next((h for h in self._print_history if h["id"] == uid), None)
        base_count = existing["count"] if existing else 0
        new_count = base_count + copies
        now = datetime.datetime.now()
        self._push_history(uid, new_count, now)

        if uid == self._unique_value:
            self._print_count   = new_count
            self._last_print_at = now
            self._apply_print_state()
        else:
            self.history_btn.config(state="normal")

        self._set_status(f"✅ 서버 검색 재출력 → {printer} ({copies}매)")
        messagebox.showinfo("재출력 완료",
                            f"코드를 {copies}매 재출력했습니다.\n"
                            f"코드: {uid}\n"
                            f"해당 QR 누적: {new_count}매",
                            parent=parent)

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
