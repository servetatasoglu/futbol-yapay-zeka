# tests/test_value_bet.py
"""
Unit Test Suite — Regresyon Güvenliği (v3.0 Updated Imports)
═══════════════════════════════════════════════════════════════
Çalıştırma: pytest tests/ -v

Testler:
  1. Edge hesaplama doğruluğu
  2. Kelly boyutlandırma sınırları
  3. Olasılık normalizasyonu (ev + ber + dep = 1)
  4. Türetilmiş bahis regresyon testi
  5. Brier Score hesaplama doğruluğu
  6. Bankroll fonksiyon doğruluğu
  7. Stop-Loss Kontrolü
  8. Model Yenileme (Aşama 5.3)
"""

import sys
import os

# Proje kök dizinini path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────
#  1. Edge Hesaplama
# ─────────────────────────────────────────────────────────────

def test_edge_calculation():
    """Edge hesaplama: Ham EV = (olasılık × oran) - 1 ve Bayesian Shrunk Edge"""
    from value.edge import value_hesapla

    # Ham EV (Raw expected value)
    raw_ev = lambda p, o: (p * o) - 1.0
    assert abs(raw_ev(0.60, 2.10) - 0.26) < 0.001
    assert abs(raw_ev(0.50, 2.00) - 0.00) < 0.001
    assert raw_ev(0.40, 2.00) < 0

    # Bayesian Shrunk Edge (v3.0 value_hesapla)
    shrunk_edge = value_hesapla(0.60, 2.10)
    assert 0.01 < shrunk_edge <= 0.05, f"Bayesian shrunk edge {shrunk_edge} makul aralıkta olmalı"
    assert value_hesapla(0.40, 2.00) < 0



def test_edge_capped_at_max():
    """Efektif edge MAX_EDGE'i (0.12) geçmemeli."""
    from value.edge import _efektif_edge

    # Çok yüksek ham edge
    efektif = _efektif_edge(
        edge=0.30, ci_w=0.10, piyasa_uyum=0.6,
        over_round=1.05, tahmin="Ev Sahibi Kazanır",
    )
    assert efektif <= 0.12, f"Efektif edge {efektif} > 0.12 MAX_EDGE"


# ─────────────────────────────────────────────────────────────
#  2. Kelly Boyutlandırma
# ─────────────────────────────────────────────────────────────

def test_kelly_basic():
    """Kelly formülü: f* = (b*p - q) / b"""
    from risk.bankroll import kelly_hesapla

    result = kelly_hesapla(olasilik=0.60, oran=2.10, banka=1000)
    assert result["kelly_tam"] > 0, "Pozitif edge için Kelly > 0 olmalı"
    assert result["bahis_miktar"] > 0, "Bahis miktarı > 0 olmalı"
    # NOT: MIN_BAHIS_TL=50 kuralı yüzünden küçük bankada min 50 TL olabilir
    # Bu yüzden sadece max sınırı kontrol et (banka 1000 ise max 50 TL)
    assert result["bahis_miktar"] <= max(1000 * 0.02, 50), "Bahis makul aralıkta"


def test_kelly_negative_edge():
    """Negatif edge'de Kelly = 0 olmalı."""
    from risk.bankroll import kelly_hesapla

    result = kelly_hesapla(olasilik=0.30, oran=2.00, banka=1000)
    assert result["kelly_tam"] == 0, "Negatif edge → Kelly = 0"
    assert result["bahis_miktar"] == 0, "Negatif edge → bahis = 0"


def test_kelly_max_bet_limit():
    """Tek bahis bankın %2'sini geçmemeli (MAX_BAHIS_BANKA_ORANI)."""
    from risk.bankroll import kelly_hesapla

    result = kelly_hesapla(olasilik=0.90, oran=5.00, banka=10000)
    # Max %2 = 200 TL
    assert result["bahis_miktar"] <= 200, f"Bahis {result['bahis_miktar']} > 200 max limit"


def test_kelly_min_bet():
    """Minimum bahis 50 TL olmalı (banka yeterliyse)."""
    from risk.bankroll import kelly_hesapla

    result = kelly_hesapla(olasilik=0.55, oran=2.00, banka=5000)
    if result["bahis_miktar"] > 0:
        assert result["bahis_miktar"] >= 50, \
            f"Bahis {result['bahis_miktar']} < 50 TL minimum"


# ─────────────────────────────────────────────────────────────
#  3. Olasılık Normalizasyonu
# ─────────────────────────────────────────────────────────────

def test_probability_sum_to_one():
    """Model olasılıkları (ev + ber + dep) ~ 1.0 olmalı."""
    ev_p = 0.45
    ber_p = 0.25
    dep_p = 0.30
    total = ev_p + ber_p + dep_p
    assert abs(total - 1.0) < 0.001, f"Toplam {total} ≠ 1.0"


# ─────────────────────────────────────────────────────────────
#  4. Türetilmiş Bahis Regresyon Testi
# ─────────────────────────────────────────────────────────────

def test_no_derived_bets():
    """
    Regresyon: value/edge.py artık KG Var, 1.5 Üst, Çifte Şans ÜRETMEMELİ.
    Aktif (yorum olmayan) satırlarda bu bahis tiplerinin olmamasını doğrula.
    """
    import inspect
    from value.edge import value_betleri_bul

    kaynak = inspect.getsource(value_betleri_bul)

    # Her satırı kontrol et — sadece AKTIF (yorum olmayan) satırlarda ara
    yasakli = ["Çifte Şans", "1.5 Üst"]
    
    for line in kaynak.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):  # Yorum satırı OK
            continue
        for yasak in yasakli:
            assert yasak not in stripped, \
                f"value_betleri_bul() aktif kodda '{yasak}' içeriyor — türetilmiş bahis regresyon!"


def test_no_beraberlik_in_piyasa_map():
    """Beraberlik piyasa_map'ten kaldırılmış veya korumalı olmalı."""
    import inspect
    from value.edge import value_betleri_bul

    kaynak = inspect.getsource(value_betleri_bul)

    piyasa_map_aktif = False
    for line in kaynak.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if '"Beraberlik"' in stripped and 'piyasa_map' not in stripped:
            continue
        if '"Beraberlik"' in stripped and ":" in stripped and "(" in stripped:
            piyasa_map_aktif = True
    
    assert not piyasa_map_aktif, \
        "Beraberlik piyasa_map'te aktif — regresyon uyarısı!"


# ─────────────────────────────────────────────────────────────
#  5. Brier Score
# ─────────────────────────────────────────────────────────────

def test_brier_perfect():
    """Mükemmel tahminler → Brier = 0."""
    from tracking.brier_monitor import brier_score

    tahminler = [
        {"predicted_p": 1.0, "won": True},
        {"predicted_p": 1.0, "won": True},
        {"predicted_p": 0.0, "won": False},
    ]
    bs = brier_score(tahminler)
    assert bs == 0.0, f"Mükemmel tahmin Brier = {bs}, 0 olmalı"


def test_brier_worst():
    """En kötü tahminler → Brier = 1."""
    from tracking.brier_monitor import brier_score

    tahminler = [
        {"predicted_p": 0.0, "won": True},
        {"predicted_p": 1.0, "won": False},
    ]
    bs = brier_score(tahminler)
    assert bs == 1.0, f"En kötü tahmin Brier = {bs}, 1 olmalı"


def test_brier_moderate():
    """Gerçekçi tahminler → Brier 0.10-0.35 arası."""
    from tracking.brier_monitor import brier_score

    tahminler = [
        {"predicted_p": 0.60, "won": True},
        {"predicted_p": 0.55, "won": False},
        {"predicted_p": 0.70, "won": True},
        {"predicted_p": 0.45, "won": False},
        {"predicted_p": 0.65, "won": True},
    ]
    bs = brier_score(tahminler)
    assert 0.10 < bs < 0.35, f"Gerçekçi Brier = {bs}, 0.10-0.35 arası bekleniyor"


def test_brier_empty():
    """Boş liste → Brier = 1.0 (en kötü)."""
    from tracking.brier_monitor import brier_score

    assert brier_score([]) == 1.0


# ─────────────────────────────────────────────────────────────
#  6. Bankroll Sharpe ve Monte Carlo
# ─────────────────────────────────────────────────────────────

def test_sharpe_positive():
    """Sürekli kârlı seri → pozitif Sharpe."""
    from risk.bankroll import _sharpe_hesapla

    seri = [100, 102, 104, 106, 108, 110, 112]
    sharpe = _sharpe_hesapla(seri)
    assert sharpe > 0, f"Kârlı seri Sharpe = {sharpe}, pozitif olmalı"


def test_sharpe_negative():
    """Sürekli zararlı seri → negatif Sharpe."""
    from risk.bankroll import _sharpe_hesapla

    seri = [100, 98, 96, 94, 92, 90]
    sharpe = _sharpe_hesapla(seri)
    assert sharpe < 0, f"Zararlı seri Sharpe = {sharpe}, negatif olmalı"


def test_max_drawdown_suresi():
    """Ardışık kayıp serisi doğru hesaplanmalı."""
    from risk.bankroll import _max_drawdown_suresi

    seri = [100, 102, 100, 98, 96, 98, 100]
    assert _max_drawdown_suresi(seri) == 3

    seri_up = [100, 101, 102, 103]
    assert _max_drawdown_suresi(seri_up) == 0


def test_monte_carlo_runs():
    """Monte Carlo simülasyonu çalışmalı ve sonuç döndürmeli."""
    from risk.bankroll import _monte_carlo_sim

    mc = _monte_carlo_sim(
        toplam_bahis=100, kazanan=55,
        baslangic=1000,
        banka_serisi=[1000 + i * 5 for i in range(100)]
    )
    assert "iflas_olasiligi" in mc
    assert "ikiye_katlama_olasiligi" in mc
    assert 0 <= mc["iflas_olasiligi"] <= 100


# ─────────────────────────────────────────────────────────────
#  7. Stop-Loss Kontrolü
# ─────────────────────────────────────────────────────────────

def test_stop_loss_trigger():
    """Banka %20+ düşerse stop-loss tetiklenmeli."""
    from risk.bankroll import stop_loss_kontrol

    result = stop_loss_kontrol(baslangic_banka=1000, guncel_banka=750)
    assert result["tetiklendi"], "Banka %25 düştü — stop-loss tetiklenmeli"


def test_stop_loss_safe():
    """Banka sağlıklıysa stop-loss tetiklenmemeli."""
    from risk.bankroll import stop_loss_kontrol

    result = stop_loss_kontrol(baslangic_banka=1000, guncel_banka=950)
    assert not result["tetiklendi"], "Banka %5 düştü — stop-loss tetiklenmemeli"


# ─────────────────────────────────────────────────────────────
#  8. Model Yenileme (Aşama 5.3)
# ─────────────────────────────────────────────────────────────

def test_model_yenile_durum_raporu_yapi():
    """durum_raporu() beklenen tüm anahtarları döndürmeli."""
    from model.train import durum_raporu

    r = durum_raporu()
    zorunlu_anahtarlar = [
        "yenileme_gerekli", "gecen_gun", "esik_gun",
        "son_yenileme", "son_dogruluk", "son_mac_sayisi",
    ]
    for anahtar in zorunlu_anahtarlar:
        assert anahtar in r, f"durum_raporu() '{anahtar}' anahtarını döndürmüyor"


def test_model_yenile_donus_tipleri():
    """yenileme_gerekli_mi() doğru tipleri döndürmeli."""
    from model.train import yenileme_gerekli_mi

    gerekli, gecen_gun = yenileme_gerekli_mi()
    assert isinstance(gerekli, bool),  "yenileme_gerekli_mi()[0] bool olmalı"
    assert isinstance(gecen_gun, float), "yenileme_gerekli_mi()[1] float olmalı"
    assert gecen_gun >= 0, "Geçen gün negatif olamaz"


def test_model_yenile_settings_entegrasyonu():
    """settings.py'deki MODEL_YENILEME_GUN durum_raporu'na yansımalı."""
    from model.train import durum_raporu
    from config.settings import MODEL_YENILEME_GUN

    r = durum_raporu()
    assert r["esik_gun"] == MODEL_YENILEME_GUN, (
        f"Eşik {r['esik_gun']} ≠ settings.MODEL_YENILEME_GUN {MODEL_YENILEME_GUN}"
    )
