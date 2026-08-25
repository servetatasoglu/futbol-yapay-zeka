# config/settings.py

import os
from pathlib import Path

# ── .env Yükle (güvenlik: API anahtarları kaynak kodda olmamalı) ──
# ── .env Yükle (güvenlik: API anahtarları kaynak kodda olmamalı) ──
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# ── API Anahtarları (.env veya çevre değişkeninden okunur) ────────
# ⚠️  Anahtarları .env dosyasına koyun, kaynak koda yazmayın!
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
ODDS_API_KEY          = os.getenv("ODDS_API_KEY",          "")
SPORTMONKS_API_KEY    = os.getenv("SPORTMONKS_API_KEY",    "")
API_FOOTBALL_KEY      = os.getenv("API_FOOTBALL_KEY",      "")
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN",        "")
TELEGRAM_CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID",      "")
TELEGRAM_AKTIF        = True

# ── Bankroll (Merkezi Kaynak) ─────────────────────────────────
# Bu değerleri main.py ve bankroll.py buradan okur — tutarsızlık yok
BANKROLL_BASLANGIC     = float(os.getenv("BANKROLL", "5000"))  # Gerçek başlangıç kasası (TL/birim)
# 🔧 DÜZELTİLDİ: Stop-loss %15 → %20 (erken uyarı, daha koruyucu)
BANKROLL_STOP_LOSS     = 0.20   # Kasa %20 erirse dur — %15 çok geç müdahale ediyordu
# 🔧 DÜZELTİLDİ: Max bahis %4 → %2 — tek bahiste max kayıp sınırı
BANKROLL_MAX_BET_ORAN  = 0.02   # Tek bahis max bankın %2'si (eski: %4 — çok agresif)
BANKROLL_MIN_BET_ORAN  = 0.005  # Tek bahis min bankın %0.5'i
BANKROLL_MIN_BET_TL    = 50.0   # Nesine/Misli alt limit
# 🔧 DÜZELTİLDİ: Kelly fraksiyon %25 → %5 (1/20-Kelly)
# Gerçek dünyada pozitif beklenti kanıtlanana kadar %5 yeterli.
# Açıklama: backtest ROI ile gerçek ROI arasındaki uçurum kapanmadan
# agresif Kelly kullanmak sermeyeyi hızla eritir.
BANKROLL_KELLY_FRAKSIYON = 0.05  # 1/20-Kelly — paper trading onaylanana kadar

# ── Model Yenileme Zamanlaması ────────────────────────────────
MODEL_YENILEME_GUN     = 7     # GBM modeli 7 günde bir yenilenir (eskisi: 30)


# ── Ligler ───────────────────────────────────────────────────
LIGLER = {
    # ✅ HEDEFLENEN ASİMETRİK / İKİNCİL PİYASALAR (GOL VE KG İÇİN)
    "FL1": {"isim": "Ligue 1",           "odds_key": "soccer_france_ligue_one",       "football_data": True,  "api_football_id": 61},
    "PPL": {"isim": "Primeira Liga",     "odds_key": "soccer_portugal_primeira_liga", "football_data": True,  "api_football_id": 94},
    "BSA": {"isim": "Brasileirao",       "odds_key": "soccer_brazil_campeonato",      "football_data": False, "api_football_id": 71},
    "TSL": {"isim": "Süper Lig",         "odds_key": "soccer_turkey_super_league",    "football_data": False, "api_football_id": 203},
    "BL2": {"isim": "2. Bundesliga",     "odds_key": "soccer_germany_bundesliga2",    "football_data": False, "api_football_id": 79},
    "ELC": {"isim": "Championship",      "odds_key": "soccer_efl_champ",              "football_data": True,  "api_football_id": 40},
    "DED": {"isim": "Eredivisie",        "odds_key": "soccer_netherlands_eredivisie", "football_data": True,  "api_football_id": 88},
}

# ════════════════════════════════════════════════════════════════
#  v3.0: INSTITUTIONAL-GRADE PARAMETERS
# ════════════════════════════════════════════════════════════════

# ── Championship Disable Flag ─────────────────────────────────
# ELC (Championship): 0% win rate in live, negative ROI in backtest.
# Disabling entirely until model proves profitable on this league.
ELC_AKTIF = False

# ── League Efficiency Factors ─────────────────────────────────
# How efficient is the Pinnacle market for each league?
# Higher = more efficient = harder to beat = more shrinkage applied
# Scale: 0.0 (inefficient) → 1.0 (perfectly efficient)
# Based on Pinnacle overround, liquidity, and historical CLV data.
LIG_VERIMLILIK = {
    "PL":  0.95,   # Premier League — most efficient market
    "PD":  0.92,   # La Liga
    "BL1": 0.90,   # Bundesliga
    "SA":  0.88,   # Serie A
    "CL":  0.93,   # Champions League
    "FL1": 0.85,   # Ligue 1
    "DED": 0.80,   # Eredivisie
    "PPL": 0.78,   # Primeira Liga
    "ELC": 0.82,   # Championship (disabled but kept for reference)
    "BSA": 0.75,   # Brasileirao
    "TSL": 0.77,   # Süper Lig
    "BL2": 0.78,   # 2. Bundesliga
}
LIG_VERIMLILIK_VARSAYILAN = 0.85

# ── Max Realistic Edge Per League ─────────────────────────────
# Anything above these thresholds is model hallucination, not real edge.
# Based on academic literature: even the best models achieve 2-5% edge.
LIG_MAX_EDGE = {
    "PL":  0.030,  # 3% — extremely efficient market
    "PD":  0.035,  # 3.5%
    "BL1": 0.040,  # 4%
    "SA":  0.040,  # 4%
    "CL":  0.035,  # 3.5%
    "FL1": 0.045,  # 4.5%
    "DED": 0.055,  # 5.5% — less efficient
    "PPL": 0.055,  # 5.5%
    "ELC": 0.050,  # 5% (disabled)
    "BSA": 0.060,  # 6%
    "TSL": 0.060,  # 6%
    "BL2": 0.055,  # 5.5%
}
LIG_MAX_EDGE_VARSAYILAN = 0.050

# ── Bayesian Edge Shrinkage ───────────────────────────────────
# p_final = α * p_model + (1-α) * p_market
# α = SHRINKAGE_BASE - league_efficiency * SHRINKAGE_MARKET_WEIGHT
# Lower α = more trust in market, less in model (conservative)
SHRINKAGE_MODEL_WEIGHT  = 0.55   # Base model weight (before league adjustment)
SHRINKAGE_MARKET_WEIGHT = 0.45   # Base market weight
# 🔧 DÜZELTİLDİ: 1.5 → 0.8 — Önceki değer çok agresif kesinti yapıyor
# %10 uncertainty × 1.5 = %15 ceza → edge %12 olsa bile negatife düşüyordu
# Yeni değer: edge_adj = edge - 0.8 × uncertainty (makul ceza)
SHRINKAGE_UNCERTAINTY_K = 0.8    # Penalty multiplier: edge_adj = edge - k * uncertainty

# ── Draw Bet Limits ────────────────────────────────────────────────────────────
# Draw bets have historically underperformed (66% of bets, poor ROI).
# Strict limits to prevent draw bias from destroying profitability.
DRAW_MAX_GUNLUK       = 1     # Max 1 draw bet per day
# 🔧 DÜZELTİLDİ: WEAK → STRONG (eski değer çok gevşekti)
DRAW_MIN_SHARP_TIER   = "STRONG"  # Draw bets require at least STRONG sharp signal
DRAW_EDGE_CARPAN      = 2.0   # Draw bets require 2x the normal edge threshold
# 🆕 YENİ: Sharp çelişki kuralı — Sharp EV/DEP varken beraberlik seçilmez
DRAW_SHARP_CONFLICT_REJECT = True  # Sharp sinyali seçimle çelişirse reddet

# ── Anti-Overfitting: Edge Cap ────────────────────────────────────────────────
# 🔧 DÜZELTİLDİ: GLOBAL_MAX_EDGE 0.08 → 0.12
# Eski değer çok sıkıydı: 31 maç bu filtreden geçemedi.
# Lig bazlı dinamik cap (LIG_MAX_EDGE) zaten daha kısıtlayıcı çalışıyor.
# Global cap sadece son güvenlik ağı olmalı — 12% makul üst sınır.
GLOBAL_MAX_EDGE       = 0.12  # 12% absolute maximum — anything higher is noise
# 🔧 DÜZELTİLDİ: GLOBAL_MIN_EDGE 0.02 → 0.015
# 1.5% minimum — lig özelinde dinamik eşikler zaten daha yüksek
GLOBAL_MIN_EDGE       = 0.015 # 1.5% minimum — below this, edge is within noise floor

# ── Poisson ──────────────────────────────────────────────────
SON_MAC_SAYISI     = 10
EV_SAHIBI_AVANTAJI = 1.06
MIN_MAC_SAYISI     = 5
REGRESS_FAKTOR     = 0.25

# ── ELO ──────────────────────────────────────────────────────
ELO_BASLANGIC          = 1500
ELO_K_FAKTOR           = 32
ELO_EV_AVANTAJI        = 65
ELO_AGIRLIK_VARSAYILAN = 0.35
ELO_AGIRLIK_YETERLI    = 0.45

# ── Monte Carlo ───────────────────────────────────────────────
MC_SIMULASYON_SAYISI  = 10_000
MC_LAMBDA_BELIRSIZLIK = 0.18
MC_AGIRLIK            = 0.35

# ── Form & Momentum ──────────────────────────────────────────
FORM_ETKI_CARPANI = 0.20
FORM_SON_MAC      = 8
FORM_DECAY_RATE   = 0.85

# ── H2H ──────────────────────────────────────────────────────
H2H_ETKI_CARPANI = 0.15
H2H_MIN_MAC      = 2

# ── Beraberlik Kalibrasyonu ───────────────────────────────────
BER_KALIBRASYON_AGIRLIK = 0.30

# ── Adaptif Ağırlık Tabanları ─────────────────────────────────
# 1X2 Piyasaları (Kim kazanır?)
AGIRLIK_ELO     = 0.40  # Güç dengesi için ELO harika
AGIRLIK_POISSON = 0.30
AGIRLIK_MC      = 0.20
AGIRLIK_FORM    = 0.05
AGIRLIK_H2H     = 0.05

# Goal Piyasaları (2.5 Üst/Alt, KG Var/Yok)
GOL_AGIRLIK_POISSON = 0.60  # Gol toplamında Poisson (ve xG) kraldır
GOL_AGIRLIK_MC      = 0.20  # Varyans için simülasyon şart
GOL_AGIRLIK_ELO     = 0.10  # ELO gol üretkenliğini iyi ölçmez, ağırlığı düşürüldü
GOL_AGIRLIK_FORM    = 0.07  # Yakın dönem gol formu daha önemli
GOL_AGIRLIK_H2H     = 0.03

# ── Value Bet Filtreleri ──────────────────────────────────────
# 🔴 v3.0 FIX: Was -0.50 (letting EVERYTHING through) → 0.03 (3% minimum edge)
# This single bug was the root cause of 32% average edge and massive overfitting.
VALUE_BET_ESIGI = 0.03   # 3% minimum edge — realistic for semi-efficient markets
MIN_ORAN        = 1.50   # Raised from 1.40 — very low odds have razor-thin margins
MAX_ORAN        = 4.00   # Raised from 3.00 — allows some value in higher odds

# ── Kupon Filtreleri ──────────────────────────────────────────
KUPON_MIN_EDGE  = 0.08
KUPON_2LI_ADET  = 3
KUPON_3LU_ADET  = 2

# ── Odds API Pencere ───────────────────────────────────
# Ücretsi tier: 500 istek/ay → 7 lig × 2 gün pencere = 14 istek/gün = 420/ay
# 2 gün yeterli: bugün + yarın maçları her zaman kapsar
ODDS_GUN_PENCERESI = 7  # 7 gün: Bu hafta maçları da kapsar. Bütçe: 13 lig × 7 gün = 91 istek/ay ✅

# 🔴 DENETİM: Veriler anlık olmalı. Gecikme CLV'yi öldürür.
# Ücretsiz tier limitlerine dikkat ederek süreyi 10 dakikaya indiriyoruz.
ODDS_CACHE_DAKIKA  = 10     # 10 dakika (gerçek zamanlı fiyatlama)
ODDS_HAREKET_DAKIKA = 10    # 10 dakika momentum takibi

# ════════════════════════════════════════════════════════════════
#  YENİ: Lig Bazında Dixon-Coles rho Parametresi
#  Açıklama: rho düşük skorlarda (0-0, 1-0, 0-1, 1-1) Poisson
#  bağımsızlık varsayımını düzeltir. Her lig farklı gol profili
#  taşır; sabit -0.10 yerine lig özelinde değer çok daha doğru.
#
#  Kalibrasyonun dayanağı:
#    PL  → savunma ağırlıklı, sıkı kapanışlar  → daha negatif rho
#    DED → Avrupa'nın en gollü ligi             → rho -0.06'ya yakın
#    ELC → yoğun takvim, yüksek skorlu maçlar  → -0.07
#    CL  → büyük güç farkı var, az beraberlik  → -0.11
# ════════════════════════════════════════════════════════════════
LIG_RHO = {
    "PL":  -0.13,   # Premier League
    "PD":  -0.11,   # La Liga
    "BL1": -0.10,   # Bundesliga
    "SA":  -0.10,   # Serie A
    "FL1": -0.09,   # Ligue 1
    "DED": -0.06,   # Eredivisie — en gollü lig
    "PPL": -0.09,   # Primeira Liga
    "ELC": -0.07,   # Championship — yoğun takvim, yüksek skorlu
    "BSA": -0.09,   # Brasileirao
    "TSL": -0.08,   # Süper Lig — orta-yüksek gol profili
    "BL2": -0.08,   # 2. Bundesliga — BL1'e yakın ama daha gollü
    "CL":  -0.11,   # Champions League
    "EL":  -0.10,   # Europa League
}
LIG_RHO_VARSAYILAN = -0.10   # Yukarıda tanımsız lig için fallback

# ════════════════════════════════════════════════════════════════
#  YENİ: Lig Bazında xG Karışım Oranı
#  Premier League'de veri çok zengin → xG ağırlığı yüksek.
#  Championship'te fiziksel oyun stili → ham gol daha önemli.
# ════════════════════════════════════════════════════════════════
LIG_XG_KARISIM = {
    "PL":  0.70,   # En iyi xG verisi, güvenilir
    "PD":  0.65,   # La Liga
    "BL1": 0.65,   # Bundesliga
    "SA":  0.65,   # Serie A
    "FL1": 0.60,   # Ligue 1
    "DED": 0.60,   # Eredivisie
    "PPL": 0.55,   # Primeira Liga
    "ELC": 0.40,   # Championship — fiziksel, xG daha az güvenilir
    "BSA": 0.45,   # Brasileirao — xG verisi sınırlı
    "TSL": 0.50,   # Süper Lig — orta kalite xG
    "BL2": 0.55,   # 2. Bundesliga — Bundesliga altyapısından veri
    "CL":  0.65,   # Champions League
    "EL":  0.60,   # Europa League
}
LIG_XG_KARISIM_VARSAYILAN = 0.60

# ════════════════════════════════════════════════════════════════
#  YENİ: Lig + Tahmin Tipi Bazında Dinamik Edge Eşikleri
#  Backtest verisi her kombinasyon için farklı ROI profili gösteriyor.
#  Beraberlik her ligde daha yüksek eşik gerektiriyor.
# ════════════════════════════════════════════════════════════════
LIG_EDGE_ESIGI = {
    # Hacmi artırmak ve Makine Öğrenimini hızlandırmak için
    # Edge (Kâr Marjı) sınırları profesyonel Hacim (Volumetrik) seviyelere çekildi.
    # lig_kodu → { "ev": eşik (Edge), "dep": eşik, "ber": eşik }
    
    # Majör Ligler (Verimli piyasa, %3.5 - %4.5 yeterli)
    "PL":  {"ev": 0.035, "dep": 0.040, "ber": 0.060},
    "PD":  {"ev": 0.035, "dep": 0.040, "ber": 0.060},
    "BL1": {"ev": 0.035, "dep": 0.040, "ber": 0.060},
    "SA":  {"ev": 0.035, "dep": 0.040, "ber": 0.060},
    
    # Avrupa Kupaları
    "CL":  {"ev": 0.040, "dep": 0.045, "ber": 0.065},
    "EL":  {"ev": 0.045, "dep": 0.050, "ber": 0.070},
    
    # Gelişim / Minör Ligler (Daha fazla fiyatlama hatası)
    "DED": {"ust": 0.040, "alt": 0.045, "kg_var": 0.045, "kg_yok": 0.050},
    "PPL": {"ust": 0.040, "alt": 0.045, "kg_var": 0.045, "kg_yok": 0.050},
    "ELC": {"ust": 0.040, "alt": 0.045, "kg_var": 0.050, "kg_yok": 0.055},
    "BSA": {"ust": 0.035, "alt": 0.040, "kg_var": 0.040, "kg_yok": 0.045},
    "TSL": {"ust": 0.035, "alt": 0.040, "kg_var": 0.040, "kg_yok": 0.045},
    "BL2": {"ust": 0.040, "alt": 0.045, "kg_var": 0.045, "kg_yok": 0.050},
    "FL1": {"ust": 0.050, "alt": 0.055, "kg_var": 0.055, "kg_yok": 0.060},
}

def get_edge_esigi(lig_kodu: str, tahmin_tipi: str) -> float:
    """
    Goal Market pivot: Lig bazlı dinamik edge eşikleri.
    
    Tahmin tipleri: "2.5 Üst", "2.5 Alt", "KG Var", "KG Yok"
    Bilinmeyen lig → sabit VALUE_BET_ESIGI (%5) fallback
    """
    if lig_kodu in LIG_EDGE_ESIGI:
        lig_esikleri = LIG_EDGE_ESIGI[lig_kodu]
        tip_map = {
            "2.5 Üst": "ust", "2.5 Alt": "alt",
            "KG Var": "kg_var", "KG Yok": "kg_yok",
            # Eski tipler için fallback (geriye uyum)
            "Ev Sahibi Kazanır": "ust", "Deplasman Kazanır": "ust",
            "Beraberlik": "alt",
        }
        tip_kisa = tip_map.get(tahmin_tipi, "ust")
        return lig_esikleri.get(tip_kisa, VALUE_BET_ESIGI)
    return VALUE_BET_ESIGI

# ════════════════════════════════════════════════════════════════
#  YENİ: Championship Yoğun Sezon Modu
#  Son 5 gün içinde oynanan maç sayısı bu eşiği geçerse yorgunluk
#  cezası otomatik devreye girer.
# ════════════════════════════════════════════════════════════════
ELC_YORGUNLUK_ESIK      = 2     # Son 5 günde 2+ maç → yorgunluk aktif
ELC_YORGUNLUK_CARPANI   = 0.93  # λ × 0.93 (-%7 gol beklentisi)

# ════════════════════════════════════════════════════════════════
#  YENİ: Genel Yorgunluk Parametreleri
# ════════════════════════════════════════════════════════════════
YORGUNLUK_PENCERE_GUN   = 7     # Son kaç gün bakılacak
YORGUNLUK_ESIK_MAC      = 2     # Kaç maç üstünde yorgunluk sayılır
YORGUNLUK_CARPANI       = 0.95  # λ çarpanı (-%5)

# ════════════════════════════════════════════════════════════════
#  YENİ: Hava Durumu Parametreleri (OpenMeteo entegrasyonu)
# ════════════════════════════════════════════════════════════════
HAVA_YAGMUR_ESIK_MM     = 2.0   # mm/saat üstü → gol azalır
HAVA_YAGMUR_CARPANI     = 0.94  # λ × 0.94
HAVA_SOGUK_ESIK_C       = 2.0   # °C altı → ek gol azalması
HAVA_SOGUK_CARPANI      = 0.97  # λ × 0.97
HAVA_CACHE_SAAT         = 3     # Hava verisi kaç saatte bir güncellenir


# ── Otomasyon Ayarları ────────────────────────────────────────
OTOMASYON_SAATLER      = ["08:00", "14:00", "17:30"]  # Günlük otomatik çalıştırma saatleri
OTOMASYON_TELEGRAM_UYARI = True  # Analiz başlamadan önce Telegram uyarısı gönder

# ── FL1 ve Beraberlik Koruması ────────────────────────────────
# FL1 backtest'te en düşük accuracy (%26.7) → neredeyse hiç tahmin çıkmasın
FL1_FILTRE_AKTIF       = True
FL1_MAX_TAHMIN         = 1     # Günde en fazla 1 FL1 tahmini
BERABERLIK_MAX_TAHMIN  = 1     # v3.0: Günde en fazla 1 beraberlik (was 2)

# ── Arbitraj Tarayıcı ─────────────────────────────────────────
ARB_AKTIF              = True
ARB_MIN_MARJ           = 0.02   # %2 üstü arbitraj anında Telegram bildir

# ── Portfolio Korelasyon ──────────────────────────────────────
# v3.0: Tightened — institutional risk management
PORTFOY_MAX_AYNI_LIG   = 1     # v3.0: Max 1 bet per league (was 2)
PORTFOY_MAX_TOPLAM     = 3     # v3.0: Max 3 total open bets (was 8)
PORTFOY_MAX_GUNLUK_EXPOSURE = 0.02  # v3.0: Max 2% daily bankroll exposure
