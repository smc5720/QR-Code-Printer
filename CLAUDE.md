# QR Code Printer

Windows용 QR 코드 생성 및 프린터 출력 데스크톱 앱. 단일 파일(`qr_printer.py`) Python 애플리케이션.

## 프로젝트 구조

```
qr_printer.py          # 전체 애플리케이션 (GUI, QR 생성, 인쇄, 자동 업데이트)
icon.ico               # 앱 아이콘
QR-Code-Printer.spec   # PyInstaller 빌드 스펙
release.sh             # 로컬 빌드 & GitHub 릴리즈 스크립트
.github/workflows/release.yml  # CI: 태그 푸시 시 자동 빌드/릴리즈
```

## 기술 스택

- **Python 3.12** (PyInstaller 호환성 — 3.13은 미지원)
- GUI: Tkinter
- QR 생성: `qrcode[pil]` + `Pillow`
- 프린터: `pywin32` (Win32 API)
- 자동 업데이트: GitHub Releases API + `urllib`
- 빌드: PyInstaller (단일 .exe)

## 빌드 & 실행

```bash
# 의존성 설치
pip install qrcode[pil] pillow pywin32

# 실행
python qr_printer.py

# exe 빌드
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico --add-data "icon.ico;." --name QR-Code-Printer qr_printer.py
```

## 릴리즈

태그 푸시 시 GitHub Actions가 자동으로 `.exe` 빌드 및 릴리즈 생성:

```bash
# qr_printer.py의 VERSION 상수를 먼저 수정할 것
git tag v1.2.0
git push origin v1.2.0
```

또는 `release.sh`로 로컬 빌드 + 릴리즈 한번에 수행.

## 코드 구조 (qr_printer.py)

| 영역 | 라인 범위 | 설명 |
|------|-----------|------|
| 자동 업데이트 | 40-118 | GitHub Releases 체크, 다운로드, 파일 교체 |
| 폰트 로드 | 124-138 | 맑은 고딕 → Arial → Consolas → Courier 폴백 |
| QR/이미지 생성 | 145-254 | 고유값 생성, QR 렌더링, 레이아웃 합성 |
| 프린터 | 261-306 | Win32 프린터 열거 및 인쇄 |
| 설정 | 313-334 | JSON 기반 문구 캐시 (`qr_printer_config.json`) |
| GUI | 341-644 | Tkinter 앱 클래스 (미리보기, 프린터 선택, 버튼) |

## 주요 규칙

- `VERSION` 상수(현재 `"1.1.0"`)는 릴리즈 태그와 반드시 일치해야 함
- 설정 파일(`qr_printer_config.json`)은 실행 파일과 같은 디렉토리에 생성됨
- 고유값 형식: `YYYYMMDD-HHMMSS-MICROSECONDS` (마이크로초 단위 정밀도)
- UI 언어: 한국어
