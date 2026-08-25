#!/usr/bin/env bash
# scripts/safe_export.sh
# ════════════════════════════════════════════════════════════
# Güvenli ZIP Export Aracı
# Projeyi sıkıştırırken .env (API anahtarları) ve diğer 
# gereksiz/geçici dosyaları dışarıda bırakır.

set -e

PROJECT_DIR=$(dirname $(dirname $(readlink -f $0)))
ZIP_NAME="futbol_bahis_sistemi_export_$(date +%Y%m%d_%H%M).zip"

echo "📦 Güvenli dışa aktarım başlatılıyor..."
echo "Hedef: $ZIP_NAME"

cd "$PROJECT_DIR"

# ZIP komutu: -r (recursive), -q (quiet)
# -x ile dışlanacak dosya kalıplarını veriyoruz
zip -r -q "$ZIP_NAME" . -x \
    "*.env" \
    "*.env.*" \
    "*.git/*" \
    "*.venv/*" \
    "*__pycache__/*" \
    "*.pytest_cache/*" \
    "*.vscode/*" \
    "*.DS_Store" \
    "*.log" \
    "*/\.git/*"

echo "✅ Dışa aktarım tamamlandı: $PROJECT_DIR/$ZIP_NAME"
echo "⚠️  UYARI: Lütfen ZIP dosyasını paylaşmadan önce içeriğini doğrulayın."
