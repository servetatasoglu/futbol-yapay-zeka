#!/bin/bash
# setup_cron.sh — v3.0 CLV Pipeline Cron Kurulumu
# ══════════════════════════════════════════════════════════════
# Bu script çalıştırıldığında:
#   1. Mevcut crontab'ı yedekler
#   2. Closing odds için her 30 dakika cron ekler
#   3. Full pipeline için sabah 08:00 cron ekler
# ══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON="$SCRIPT_DIR/local_daemon.sh"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚙️  Cron Kurulumu — Betting Engine v3.0"
echo "   Script dizini: $SCRIPT_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Mevcut crontab'ı yedekle
BACKUP="$SCRIPT_DIR/logs/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"
mkdir -p "$SCRIPT_DIR/logs"
crontab -l > "$BACKUP" 2>/dev/null || true
echo "📦 Mevcut crontab yedeklendi: $BACKUP"

# Mevcut betting engine cron'larını kaldır (tekrar eklemekten kaçın)
CLEANED=$(crontab -l 2>/dev/null | grep -v "local_daemon.sh")

# Yeni cron'ları ekle
NEW_CRON="$CLEANED
# ── Betting Engine v3.0 ──
# Closing odds: her 30 dakikada (CLV tracking için kritik)
*/30 * * * * cd '$SCRIPT_DIR' && bash local_daemon.sh closing_only >> logs/closing_cron.log 2>&1
# Full pipeline: Sabah 08:00
0 8 * * * cd '$SCRIPT_DIR' && bash local_daemon.sh full >> logs/full_pipeline.log 2>&1
# Full pipeline: Öğleden sonra 13:00 (ikinci run)
0 13 * * * cd '$SCRIPT_DIR' && bash local_daemon.sh full >> logs/full_pipeline.log 2>&1
"

echo "$NEW_CRON" | crontab -

echo "✅ Cron'lar başarıyla kuruldu:"
echo ""
crontab -l | grep -A1 "Betting Engine"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Kontrol: crontab -l"
echo "📊 Log takibi: tail -f logs/closing_cron.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
