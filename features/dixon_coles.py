# features/dixon_coles.py
import math
from collections import defaultdict

def dinamik_rho_hesapla(lig_kodu: str, maclar: list) -> float:
    """
    Ligdeki son maçlara bakarak Dixon-Coles Bivariate Poisson `rho` katsayısını hesaplar.
    Bu katsayı, ev sahibi ve deplasman golleri arasındaki korelasyonu (özellikle düşük skorlarda) modeller.
    """
    if not maclar or len(maclar) < 50:
        from config.settings import LIG_RHO, LIG_RHO_VARSAYILAN
        return LIG_RHO.get(lig_kodu, LIG_RHO_VARSAYILAN)

    ev_gol_toplam = 0
    dep_gol_toplam = 0
    mac_sayisi = 0
    
    # Gerçekleşen 0-0, 1-0, 0-1, 1-1 skorlarının frekansı
    freq_00 = 0
    freq_10 = 0
    freq_01 = 0
    freq_11 = 0

    for mac in maclar[-200:]: # Son 200 maç
        try:
            hg = int(mac["score"]["fullTime"]["home"])
            dg = int(mac["score"]["fullTime"]["away"])
        except (KeyError, TypeError, ValueError):
            continue
            
        ev_gol_toplam += hg
        dep_gol_toplam += dg
        mac_sayisi += 1
        
        if hg == 0 and dg == 0: freq_00 += 1
        elif hg == 1 and dg == 0: freq_10 += 1
        elif hg == 0 and dg == 1: freq_01 += 1
        elif hg == 1 and dg == 1: freq_11 += 1

    if mac_sayisi < 50:
        from config.settings import LIG_RHO, LIG_RHO_VARSAYILAN
        return LIG_RHO.get(lig_kodu, LIG_RHO_VARSAYILAN)

    # Ortalama lambda (gol beklentisi)
    lam_h = ev_gol_toplam / mac_sayisi
    lam_a = dep_gol_toplam / mac_sayisi
    
    if lam_h == 0 or lam_a == 0:
        return 0.0

    # Bağımsız Poisson Olasılıkları
    def poisson_p(lam, k):
        return (lam**k * math.exp(-lam)) / math.factorial(k)
        
    p_00_ind = poisson_p(lam_h, 0) * poisson_p(lam_a, 0)
    
    # Gerçek frekans
    p_00_gercek = freq_00 / mac_sayisi
    
    # Dixon-Coles tau formülü: tau(0,0) = 1 - lam_h * lam_a * rho
    # Gerçek P(0,0) = Ind_P(0,0) * (1 - lam_h * lam_a * rho)
    # rho = (1 - P(0,0)_gercek / Ind_P(0,0)) / (lam_h * lam_a)
    
    try:
        if p_00_ind > 0:
            oran = p_00_gercek / p_00_ind
            rho_tahmin = (1 - oran) / (lam_h * lam_a)
        else:
            rho_tahmin = -0.10
            
        # Rho için makul sınırlar [-0.3, 0.1]
        rho_tahmin = max(-0.30, min(0.10, rho_tahmin))
        return round(rho_tahmin, 3)
    except ZeroDivisionError:
        from config.settings import LIG_RHO, LIG_RHO_VARSAYILAN
        return LIG_RHO.get(lig_kodu, LIG_RHO_VARSAYILAN)
