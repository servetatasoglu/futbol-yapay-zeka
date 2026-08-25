#!/bin/bash
# local_daemon.sh — v3.0
# ══════════════════════════════════════════════════════════════
# Institutional Betting Engine — Otonom Günlük Çalışıcı
# ══════════════════════════════════════════════════════════════
#
# CRON KURULUMU (closing odds her 30 dakikada):
#   */30 * * * * cd /path/to/claod\ futbol && bash local_daemon.sh closing_only
#   0 8 * * *   cd /path/to/claod\ futbol && bash local_daemon.sh full
#
# KULLANIM:
#   bash local_daemon.sh          → full pipeline
#   bash local_daemon.sh closing_only → sadece closing odds güncelle
# ══════════════════════════════════════════════════════════════

cd "$(dirname "$0")"
source .venv/bin/activate 2>/dev/null || true
export PYTHONPATH="."
mkdir -p logs

ZAMAN=$(date '+%Y-%m-%d %H:%M:%S')
MOD=${1:-full}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 BETTING ENGINE v3.0 — ${MOD^^} — $ZAMAN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── CLOSING ODDS (her 30 dakikada çalışır) ──────────────────
# v3.0: Yeni closing_odds.py | separator, 4h pencere, timeline entegrasyonu
echo "📡 Kapanış Oranları & CLV Snapshot Alınıyor..."
python -c "
from data.closing_odds import kapanis_oranlarini_getir
n = kapanis_oranlarini_getir()
print(f'  → {n} closing odds kaydı güncellendi')
" 2>> logs/closing_odds.log

# Sadece closing odds modundaysa buradan çık
if [ "$MOD" = "closing_only" ]; then
    echo "✅ Closing odds güncellendi ($(date '+%H:%M:%S'))"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

# ── FULL PIPELINE ────────────────────────────────────────────

# 0. Sistem Sağlık Kontrolü
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🏥 Sistem Sağlık Kontrolü..."
python -c "
from monitoring.system_health import health_check
r = health_check(verbose=True)
if r.get('critical'):
    print('CRITICAL ALERTS — pipeline will run in analysis mode')
" 2>&1 | tee -a logs/health.log

# 0b. GBM Model Yaş Kontrolü ve Otonom Eğitim
MODEL_FILE="data/gbm_model.pkl"
EGITIM_YAPILACAK=false

if [ ! -f "$MODEL_FILE" ]; then
    echo "⚠️ GBM Modeli bulunamadı! İlk eğitim başlatılıyor..."
    EGITIM_YAPILACAK=true
else
    if stat -f "%m" "$MODEL_FILE" >/dev/null 2>&1; then
        MODEL_ZAMAN=$(stat -f "%m" "$MODEL_FILE")
    else
        MODEL_ZAMAN=$(stat -c %Y "$MODEL_FILE")
    fi
    SIMDI=$(date +%s)
    FARK=$((SIMDI - MODEL_ZAMAN))
    YEDI_GUN=$((7 * 24 * 60 * 60))

    if [ "$FARK" -gt "$YEDI_GUN" ]; then
        echo "⚠️ GBM Modeli 7 günden eski! Otonom yeniden eğitim..."
        EGITIM_YAPILACAK=true
    fi
fi

if [ "$EGITIM_YAPILACAK" = true ]; then
    echo "🧠 Model Eğitimi Başlatılıyor..."
    python model/train.py 2>&1 | tee -a logs/training.log
    echo "✅ Eğitim Tamamlandı."
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Drift Tespiti
echo "📡 Drift Tespiti Çalışıyor..."
python -c "
from tracking.drift_detector import full_drift_raporu
r = full_drift_raporu()
print(f'  Model drift: {r[\"model\"].get(\"drift\", False)}')
print(f'  Calibration drift: {r[\"calibration\"].get(\"drift\", False)}')
print(f'  Market: {r[\"market\"].get(\"trend\", \"?\")}')
if r.get('alerts'):
    for a in r['alerts']: print(f'  ⚠️  {a}')
" 2>&1 | tee -a logs/drift.log

# 2. Maç Sonuçlarını Çöz (CLV validasyonu + gerçek P&L)
echo "🔍 Maç Sonuçları Doğrulanıyor..."
python scripts/result_resolver.py --days 7 2>&1 | tee -a logs/results.log

# 3. Ana Pipeline (veri, model, sinyal, Telegram)
echo "⚙️ Ana Pipeline (main.py) Çalıştırılıyor..."
python main.py 2>&1 | tee -a logs/main.log

# 4. Closing Odds — Maç başladıktan SONRA da bir kez daha güncelle
echo "📡 Post-Kickoff CLV Snapshot..."
python -c "
from data.closing_odds import kapanis_oranlarini_getir
n = kapanis_oranlarini_getir()
print(f'  → {n} post-kickoff odds kaydı')
" 2>> logs/closing_odds.log

# 5. Timeline temizliği (7 günden eski kayıtları sil)
python -c "
from data.odds_timeline import eski_kayitlari_temizle
n = eski_kayitlari_temizle()
if n: print(f'  🧹 {n} eski timeline kaydı silindi')
" 2>/dev/null

# 6. Dashboard Güncelle
echo "📈 Web Dashboard Güncelleniyor..."
python generate_dashboard.py 2>&1 | tee -a logs/dashboard.log

echo ""
echo "✅ GÜNLÜK GÖREVLER TAMAMLANDI — $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

