import math

def poisson_prob(lmbda, k):
    """Poisson olasılık kütle fonksiyonu"""
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def poisson_cdf(lmbda, k):
    """Poisson birikimli dağılım fonksiyonu"""
    return sum(poisson_prob(lmbda, i) for i in range(k + 1))

def hesapla_alt_ust_kg(ev_xg, dep_xg, ev_xga, dep_xga, rho=-0.10):
    """
    xG verilerini kullanarak Dixon-Coles düzeltmeli Poisson dağılımı ile 
    Alt/Üst 2.5 ve Karşılıklı Gol (KG) olasılıklarını hesaplar.
    
    Dixon-Coles düzeltmesi: Düşük skorlarda (0-0, 1-0, 0-1, 1-1) Poisson'un
    bağımsızlık varsayımını düzeltir. rho parametresi lig bazında kalibre edilir.
    
    Parametreler:
        ev_xg:   Ev sahibi beklenen gol (xG)
        dep_xg:  Deplasman beklenen gol (xG)
        ev_xga:  Ev sahibi beklenen yenilen gol (xGA)
        dep_xga: Deplasman beklenen yenilen gol (xGA)
        rho:     Dixon-Coles düzeltme parametresi (lig bazlı, varsayılan -0.10)
    """
    # Beklenen goller (atılan ve yenilenin ortalaması)
    lambda_ev = (ev_xg + dep_xga) / 2.0
    lambda_dep = (dep_xg + ev_xga) / 2.0
    
    # Bağımsız Poisson kabulüyle toplam gol beklentisi
    lambda_top = lambda_ev + lambda_dep
    
    # ── Dixon-Coles düzeltme fonksiyonu ──────────────────────────
    # tau(x, y, lambda1, lambda2, rho): düşük skorlarda olasılık düzeltmesi
    def dc_tau(x, y, lam1, lam2, r):
        """Dixon-Coles tau düzeltme çarpanı."""
        if x == 0 and y == 0:
            return 1.0 - lam1 * lam2 * r
        elif x == 0 and y == 1:
            return 1.0 + lam1 * r
        elif x == 1 and y == 0:
            return 1.0 + lam2 * r
        elif x == 1 and y == 1:
            return 1.0 - r
        return 1.0  # x >= 2 veya y >= 2 → düzeltme yok
    
    # ── Ortak skor matrisi (0-7 gol aralığı) ─────────────────────
    MAX_GOL = 8
    skor_matrisi = {}
    toplam_p = 0.0
    
    for i in range(MAX_GOL):
        for j in range(MAX_GOL):
            p_baz = poisson_prob(lambda_ev, i) * poisson_prob(lambda_dep, j)
            tau = dc_tau(i, j, lambda_ev, lambda_dep, rho)
            p_duzeltilmis = p_baz * tau
            # Negatif olasılık önleme (rho çok negatifse olabilir)
            p_duzeltilmis = max(0.0, p_duzeltilmis)
            skor_matrisi[(i, j)] = p_duzeltilmis
            toplam_p += p_duzeltilmis
    
    # Normalize et (toplam = 1.0 olsun)
    if toplam_p > 0:
        for key in skor_matrisi:
            skor_matrisi[key] /= toplam_p
    
    # ── 2.5 Üst/Alt Olasılığı ────────────────────────────────────
    p_under25 = sum(
        skor_matrisi.get((i, j), 0)
        for i in range(MAX_GOL)
        for j in range(MAX_GOL)
        if i + j <= 2
    )
    p_over25 = 1.0 - p_under25
    
    # ── KG Var/Yok Olasılığı ─────────────────────────────────────
    p_btts_no = sum(
        skor_matrisi.get((i, j), 0)
        for i in range(MAX_GOL)
        for j in range(MAX_GOL)
        if i == 0 or j == 0
    )
    p_btts_yes = 1.0 - p_btts_no
    
    return {
        "p_over25": p_over25,
        "p_under25": p_under25,
        "p_btts_yes": p_btts_yes,
        "p_btts_no": p_btts_no,
        "lambda_ev": lambda_ev,
        "lambda_dep": lambda_dep,
        "lambda_top": lambda_top
    }

def analiz_metni_uret(tahmin, p_shrunk, market_p, edge, tier, lambda_top, fake_edge_score=0.0):
    """
    Her tahmin için doğal dilde analiz gerekçesi üretir.
    """
    satirlar = []
    
    # 1. Model vs Piyasa
    fark_pct = round((p_shrunk - market_p) * 100, 1)
    if fark_pct > 0:
        satirlar.append(f"Model piyasadan %{fark_pct} daha yüksek ihtimal veriyor.")
    else:
        satirlar.append("Değer ağırlıklı olarak keskin oran hareketinden kaynaklanıyor.")
        
    # 2. xG (Gol Beklentisi) Yorumu
    if lambda_top > 0:
        if lambda_top < 2.2:
            satirlar.append(f"Düşük xG profili (Beklenti: {lambda_top:.2f} gol) → Sıkı maç bekleniyor.")
        elif lambda_top > 3.0:
            satirlar.append(f"Yüksek xG profili (Beklenti: {lambda_top:.2f} gol) → Bol pozisyonlu bir maç.")
        else:
            satirlar.append(f"Dengeli xG profili (Beklenti: {lambda_top:.2f} gol).")
            
    # 3. Sharp Money (Keskin Para)
    if tier in ("ELITE", "STRONG"):
        satirlar.append("Keskin bahisçiler (Sharp money) bu yönde pozisyon alıyor.")
    elif tier == "WEAK":
        satirlar.append("Piyasada bu tahmine hafif bir para akışı var.")
    else:
        if edge > 0.10:
            satirlar.append("Sinyal tamamen modelin bulduğu matematiksel değere (Edge) dayanıyor.")
            
    # 4. Sentetik/Risk Yorumu
    if fake_edge_score > 0:
        satirlar.append("Dikkat: Veri seti eksiklikleri sentetik dolduruldu.")
        
    return " | ".join(satirlar)
