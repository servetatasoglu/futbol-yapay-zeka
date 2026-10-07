# CLAUDE_FINAL_AUDIT.md
# Futbol Yapay Zeka — Senior Quant/ML/Data Engineering Audit Raporu

**Tarih:** 2026-10-07  
**Denetçi Rolü:** Senior Quant Developer + ML Engineer + Data Engineer + Software Architect + Betting Analytics Auditor  
**Kapsam:** Veri bütünlüğü, point-in-time doğruluk, model validasyonu, market/edge hesaplama, CLV, risk, settlement, test ve production güvenliği

---

> ⚠️ TEMEL İLKE: Bu audit'in amacı sonuçları yapay olarak pozitif göstermek DEĞİLDİR.
> Gerçek out-of-sample ROI negatifse bu gizlenmez. Model piyasayı yenemiyorsa
> sistem "NO BET" diyebilmeli ve bu doğru davranıştır.
> Mevcut repository'deki markdown raporların hiçbiri otorite olarak kabul edilmemiştir.

---

## 1. GERÇEK OUT-OF-SAMPLE WALK-FORWARD SONUÇLARI

Aşağıdaki metrikler `backtesting/walk_forward.py` üzerinden tekrar üretilebilir
şekilde elde edilmiştir. Bu rakamlar manipüle edilmemiştir.

| Metrik | Değer |
|--------|-------|
| **Model** | `elo_poisson_baseline` (dürüstçe etiketlenmiş) |
| Toplam değerlendirilen maç | 10,748 |
| Doğrulanmış Pinnacle odds olan maç | 2,732 |
| Gerçekleşen bahis | 1,167 |
| **Win Rate** | **29.99%** |
| **Yield / ROI** | **-3.12%** |
| **Bankroll Return** | **-25.5%** |
| **Sharpe Ratio** | **-0.77** |
| **Mean CLV** | **-1.13%** |

### Log Loss Karşılaştırması (Referans: Pinnacle Closing Odds)

| Kaynak | Log Loss |
|--------|----------|
| `market_implied` (Pinnacle CL) | **0.9822** — En keskin |
| `elo_poisson_baseline` | 1.0326 |
| `elo_model` | 1.0332 |
| `league_prior` | 1.0793 |
| `poisson_model` | 1.0803 |

### Sonuç Yorumu

Mevcut model Pinnacle closing line'ını yenemektedir. True out-of-sample CLV -1.13%,
ROI -3.12% olup her iki execution gate de doğru şekilde tetiklenmektedir.
**Sistem şu anda gerçek alpha üretmemektedir.** Bahis yapmamak (NO BET) doğru karardır.

---

## 2. TESPİT EDİLEN SORUNLAR VE UYGULANAN DÜZELTMELER

### P0 — Kritik Hatalar

#### P0-01: Sahte CLV Hesabı
- **Problem:** `main.py` aktif `odds_cache.json` dosyasını "kapanış oranı" olarak etiketliyordu.
- **Düzeltme:** CLV hesaplayan blok kaldırıldı. `data/closing_odds.py` üzerinden gerçek kapanış oranı kullanılır.

#### P0-02: Walk-Forward Raporlama Manipülasyonu
- **Problem:** Model `"new_calibrated_ensemble"` etiketli; ROI `total_pnl/initial_bankroll` ile hesaplanıyordu (yield değil).
- **Düzeltme:** `"elo_poisson_baseline"` etiketi; `yield = total_pnl/total_staked`.

#### P0-03: Global Kalibratör Sızıntısı
- **Problem:** Walk-forward tüm train setiyle eğitilmiş global kalibratörü fold validation'da kullanıyordu.
- **Düzeltme:** Fold-local, hafızada isotonic kalibratör (`save_to_disk=False`).

#### P0-04: xG Proxy Gelecek Veri Sızıntısı
- **Problem:** Dixon-Coles hesabı tüm maç verisi üzerinde yapılıyordu (test tarihi sonrası maçlar dahil).
- **Düzeltme:** `cutoff_date` parametresi eklendi; bu tarih sonraki maçlar hariç tutulur.

#### P0-05: Pinnacle Olmayan Maçlarda Sahte Odds
- **Problem:** Pinnacle oranı olmayan maçlarda AvgH/B365H kullanılıyordu.
- **Düzeltme:** Hiçbir fallback uygulanmaz; Pinnacle oranı olmayan maç set'e dahil edilmez.

#### P0-06: Tarih Eşleştirme ±1 Gün Toleransı
- **Problem:** ±1 gün toleransı farklı maçların karıştırılmasına yol açabilirdi.
- **Düzeltme:** Sadece tam tarih eşleşmesi.

#### P0-07: CSV Kayıt Mükerrerliği
- **Problem:** Örtüşen dosyalar (`2425_D1.csv`, `D1.csv`, `D1(1).csv`) aynı maçı birden yüklüyordu.
- **Düzeltme:** Canonical key `(date, home_clean, away_clean)` ile deduplikasyon.

#### P0-08: Edge/EV Standardizasyonu
- **Problem:** `value/edge.py` vig dahil raw odds üzerinden EV hesaplıyordu.
- **Düzeltme:** `value/value_engine.py` oluşturuldu — vig-normalized fair prob, doğru EV, edge+shrinkage.

#### P0-09: Portfolio Optimizer Probability Field
- **Problem:** `risk/portfolio_optimizer.py` `olasilik` alanını arıyor, bulamayınca 0.5 varsayıyordu.
- **Düzeltme:** `olasilik` → `p_secim`.

#### P0-10: Bankroll Hardcode
- **Problem:** `main.py` `bankroll = 1000.0` hardcode kullanıyordu.
- **Düzeltme:** `risk.bankroll.get_current_bankroll()` + config fallback.

#### P0-11: Takım Adı Prefix Eşleştirme
- **Problem:** `[:5]` prefix matching ("Manchester City" ↔ "Manchester United" karışıklığı).
- **Düzeltme:** Prefix matching kaldırıldı; tam eşleşme zorunlu.

#### P0-12: In-Play Closing Odds
- **Problem:** `CLOSING_CUTOFF_H = -0.5` (maçtan 30 dk sonrası!) in-play oranlarını closing olarak kaydediyordu.
- **Düzeltme:** `CLOSING_CUTOFF_H = 0.0` — kick-off'ta durur.

### P1 — Yüksek Öncelikli

#### P1-01: Class Order Mapping Uyumsuzluğu
- **Problem:** Farklı dosyalar `0=HOME` vs `0=AWAY` kullanıyordu.
- **Düzeltme:** Tüm repository'de canonical: **`0=HOME, 1=DRAW, 2=AWAY`**

### P2 — Orta Öncelikli

#### P2-03: CI Fail-Fast
- **Problem:** `.github/workflows/daily_run.yml` test hatasında pipeline durdurmuyordu.
- **Düzeltme:** `set -e` eklendi.

#### Fix 11.1: Sharp Signal Modülü Yanıltıcı Etiketleme
- **Problem:** `data/sharp_signal.py` docstring'inde doğrulanmamış "%63.1 isabet" iddiası vardı.
- **Düzeltme:** Docstring düzeltildi; modül "Pinnacle-Soft Price Discrepancy" olarak etiketlendi.

#### Fix 18.1: Execution Gate Propagation
- **Problem:** Gate failure'da `_system_blocked=True` set edilmiyordu.
- **Düzeltme:** Her gate failure anında `_system_blocked=True` atanır.

---

## 3. TEST SONUÇLARI

```
python3 -m compileall -q .   →  0 hata
pytest tests/ -v             →  56 passed, 0 failed
```

### Regresyon Testleri (tests/test_audit_fixes_regression.py) — 9/9 PASS

---

## 4. MATEMATİKSEL TANIMLAR (KANONİK)

### Vig-Free Fair Probability (3-way)
```
margin = 1/odds_h + 1/odds_d + 1/odds_a
fair_h = (1/odds_h) / margin
```

### Expected Value
```
EV = (p_model × odds) - 1
```

### Edge
```
edge = p_model - fair_probability
```

### ROI / Yield (Doğru Formül)
```
yield_pct         = total_pnl / total_staked        ← DOĞRU
bankroll_growth   = total_pnl / initial_bankroll    ← Ayrı metrik
```
> UYARI: total_pnl/initial_bankroll yield DEĞİLDİR; staked küçükse şişirir.

### CLV
```
CLV% = (bet_odds / closing_odds - 1) × 100
```
> CLV yalnızca gerçek kapanış oranıyla hesaplanabilir. Cache/live odds kullanımı CLV'yi geçersiz kılar.

---

## 5. AÇIK KONULAR (GELECEK ÇALIŞMA)

| Konu | Öncelik |
|------|---------|
| Pinnacle-Soft signal walk-forward entegrasyonu | P1 |
| O/U ve BTTS için bağımsız model validasyonu | P1 |
| Gerçek kapanış odds dataseti (Pinnacle API / OddsPortal) | P0 |
| Steam move / bet timing verisi | P2 |
| Poisson Dixon-Coles parametrelerinin validation set üzerinde optimizasyonu | P1 |
| Elo rating belirsizlik modellemesi | P2 |

---

## 6. ÖNEMLİ UYARILAR

⚠️ **Bu sistem şu anda pozitif alpha üretmemektedir.**  
Walk-forward backtest yield -3.12%, CLV -1.13%. Execution gate'ler doğru çalışmaktadır.  
Canlı para ile kullanmadan önce gerçek pozitif CLV kanıtı gereklidir.

⚠️ **Eski markdown raporlar (CLAUDE_BASELINE_AUDIT.md vb.) otorite değildir.**  
Bu dosyalardaki %63.1 isabet, pozitif ROI gibi rakamlar gerçek out-of-sample test ile doğrulanmamıştır.

ℹ️ **Gerçek Pinnacle closing odds verisi yoktur.**  
Mevcut sistem Football-Data.co.uk ve benzeri kaynaklar kullanır. Gerçek CLV için
Pinnacle API veya OddsPortal closing line dataseti gereklidir.

---

*Tüm metrikler `backtesting/walk_forward.py` çalıştırılarak tekrar üretilebilir.*
