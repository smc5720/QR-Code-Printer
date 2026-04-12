#!/bin/bash
# 로컬 빌드 & 릴리즈 스크립트
set -e

VERSION=$(grep -oP 'VERSION\s*=\s*"\K[^"]+' qr_printer.py)
TAG="v${VERSION}"

echo "=== QR Code Printer 빌드 & 릴리즈 ==="
echo "버전: ${VERSION}"
echo "태그: ${TAG}"
echo ""

# 1. exe 빌드
echo "[1] exe 빌드 중..."
pyinstaller --onefile --windowed --name QR-Code-Printer qr_printer.py
echo "  → dist/QR-Code-Printer.exe 생성 완료"
echo ""

# 2. 릴리즈 여부 확인
read -p "GitHub에 릴리즈를 생성하시겠습니까? (y/n): " answer
if [[ "$answer" != "y" ]]; then
    echo "빌드만 완료. 릴리즈는 생략합니다."
    exit 0
fi

# 3. 커밋되지 않은 변경 확인
if [[ -n $(git status --porcelain) ]]; then
    echo "커밋되지 않은 변경사항이 있습니다. 먼저 커밋해주세요."
    git status --short
    exit 1
fi

# 4. 태그 생성 & 푸시
echo "[2] 태그 ${TAG} 생성 및 푸시 중..."
git tag "${TAG}"
git push origin "${TAG}"

# 5. 릴리즈 생성
echo "[3] GitHub 릴리즈 생성 중..."
gh release create "${TAG}" \
    --title "${TAG}" \
    --generate-notes \
    qr_printer.py dist/QR-Code-Printer.exe

echo ""
echo "완료! https://github.com/smc5720/QR-Code-Printer/releases/tag/${TAG}"
