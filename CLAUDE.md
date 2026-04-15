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
- API 연동: `urllib` (재고 관리 시스템 대기열 API)
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
git tag v1.7.1
git push origin v1.7.1
```

또는 `release.sh`로 로컬 빌드 + 릴리즈 한번에 수행.

## 코드 구조 (qr_printer.py)

| 영역 | 라인 범위 | 설명 |
|------|-----------|------|
| 자동 업데이트 | 42-162 | GitHub Releases 체크, 다운로드, 검증, 파일 교체 (.exe는 .bat 통해 교체) |
| 폰트 로드 | 165-195 | 맑은 고딕/Arial/Consolas/Courier 패밀리 + Bold 폴백 |
| 고유값/QR/이미지 생성 | 198-321 | Base36 고유값 생성, QR 렌더링, 상단/하단 문구 레이아웃 합성 |
| 프린터 | 324-376 | Win32 프린터 열거 및 인쇄 (copies 파라미터로 N매 인쇄) |
| 설정 | 379-427 | JSON 기반 config (`%LOCALAPPDATA%\QR-Code-Printer\qr_printer_config.json`) + 구 경로 마이그레이션 |
| API 클라이언트 | 430-484 | 코드 중복 확인(`api_check_code`), 대기열 등록(`api_register_code`), API 키 해석 |
| GUI | 488-1303 | `QRPrinterApp(tk.Tk)` — 미리보기·프린터 선택·폰트/수량/방향·경고 배너·이력 팝업·API 연동 출력·자동 업데이트 |

## 주요 규칙

- `VERSION` 상수(현재 `"1.7.1"`)는 릴리즈 태그와 반드시 일치해야 함
- 설정 파일: `%LOCALAPPDATA%\QR-Code-Printer\qr_printer_config.json` (구 버전의 실행 파일 옆 경로에서 자동 마이그레이션됨)
- 고유값 형식: **epoch μs → Base36 대문자 (`zfill(10)` 로 최소 10자 보장)**. 예: `HHK7JCTL6N`
  - 2085년까지 자연스럽게 10자 유지, 이후 11자
  - QR alphanumeric 모드에 최적화 (대문자 + 숫자만 사용)
- UI 언어: 한국어
- 창 크기: 가로 600px 고정, 세로는 `_refit_height()` 로 컨텐츠에 맞춰 자동 조절

## 주요 규칙 (API)

- **API 연동 대상**: `https://kfrental.com` 재고 관리 시스템 대기열 API
- **API 키**: 빌드 시 GitHub Actions 시크릿(`QR_PRINTER_API_KEY`)으로 주입. 로컬에선 config `"api_key"` 또는 환경 변수 `QR_PRINTER_API_KEY`로 설정 가능
- **API 키 없으면** API 호출을 건너뛰고 기존처럼 바로 출력

## 주요 기능 플로우

- **최초 출력 (API 연동)**: `_print()` → `_print_with_api_check()` → 모달 다이얼로그에서 백그라운드 스레드로 코드 중복 확인(`GET check`) → 대기열 등록(`POST register`) → 성공 후 `_execute_print_and_update()` 로 인쇄. 중복 시 자동 재생성 + 재시도 (최대 5회). 네트워크 오류 시 경고 후 등록 없이 출력 허용
- **추가 출력/이력 재출력**: API 호출 없이 기존대로 바로 인쇄 (`_execute_print_and_update`, `_reprint_from_history`)
- **출력 상태 추적** (`_print_count`, `_last_print_at`): 출력 후 경고 배너 + "추가 출력"으로 버튼 전환 → 상품 전환 시 동일 QR 재사용 방지
- **재출력 확인**: 이미 출력된 QR을 다시 출력하려 하면 `messagebox.askyesno` 로 의도 확인
- **출력 이력** (`_print_history`): 최근 20건 config에 영속화. 팝업(`_show_history`)에서 선택 → 재출력 가능 (`_reprint_from_history`)
- **인쇄 작업 핵심**: `_do_print(uid, copies)` 헬퍼가 실제 인쇄를 수행, `_print`와 `_reprint_from_history` 가 공유
- **자동 업데이트**: 앱 시작 1초 후 백그라운드 스레드로 1회 체크 (`_check_update_background`)
