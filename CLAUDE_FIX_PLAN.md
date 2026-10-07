# CLAUDE FIX PLAN
**Repository:** futbol-yapay-zeka-main  
**Oluşturulma:** 2026-10-07  
**Temel Prensip:** Gerçeği gizleme. Negatif ROI ise söyle. Alpha yoksa söyle.

---

## FAZ 1 — BASELINE AUDIT ✅ TAMAMLANDI
Bulgular: CLAUDE_BASELINE_AUDIT.md

---

## FAZ 2 — FIXTURE IDENTITY + DEDUP + TEAM MATCHING

### Fix 2.1: Pinnacle CSV Dedup [P0-07]
**Sorun:** D1.csv = 2425_D1.csv içeriği, D1(1).csv = 2324_D1.csv kopyası.  
**Fix:** load_pinnacle_historical_odds() içinde canonical fixture ID üzerinden dedup.  
**Test:** duplicate fixture → exactly one record (deterministic).

### Fix 2.2: +-1 Day Matching Kaldır [P0-06]
**Sorun:** match_pinnacle_odds() +-1 gün toleransı ile yanlış maç eşleştirebilir.  
**Fix:** Tarih toleransını sıfıra indir. Sadece exact date match.  
**Test:** Aynı takımlar farklı günlerde → sadece doğru gün eşleşir.

### Fix 2.3: Pinnacle Fallback Kaldır [P0-05]
**Sorun:** PSH yoksa B365H alınıp "Pinnacle" gibi etiketleniyor.  
**Fix:** PS odds yoksa → missing_pinnacle, use_real_odds_only'de reject.  
**Test:** B365 var PS yok → missing_pinnacle, asla "pinnacle" etiketi almaz.

### Fix 2.4: 5-Karakter Team Matching Kaldır [P0-11]
**Sorun:** `ch[:5] == ev_c[:5]` — Paris = Parma yanlış eşleşmesi.  
**Fix:** Substring/prefix matching kaldır, sadece substring-contains yerine tam normalleştirilmiş isim karşılaştırması.  
**Test:** "Paris" "Parma"ya eşleşmemeli.

---

## FAZ 3 — PINNACLE DATA INTEGRITY ✅ FAZ 2'DE KAPSANIYOR

---

## FAZ 4 — POINT-IN-TIME xG / ROLLING / ELO

### Fix 4.1: xG Future Leakage Kaldır [P0-04]
**Sorun:** xg_proxy.py `datetime.utcnow()` bazlı, tüm geçmiş+güncel veri.  
**Fix:** `xg_proxy_hesapla(cutoff_date)` parametresi ekle. Historical backtest için cutoff kullan.  
**Test:** 2023 feature için 2024+ data silinirse xG değeri değişmemeli.

### Fix 4.2: Rolling Features Point-in-Time Doğrulama
**Sorun:** rolling_features_uret() output son durumu gösteriyor.  
**Fix:** rolling_features_point_in_time() fonksiyonunun gerçekten PIT olduğunu test et.  
**Test:** T anındaki feature T+1 verisinden etkilenmemeli.

---

## FAZ 5 — TEMPORAL LEAKAGE CONTRACT

### Fix 5.1: Temporal Validation Helper
**Yeni dosya:** `validation/temporal_contract.py`  
Her bet için: `feature_time <= prediction_time <= entry_time < kickoff`.  
Closing: `entry_time < closing_snapshot_time <= kickoff`.

---

## FAZ 6 — CANONICAL MODEL PREDICTION SERVICE

### Fix 6.1: Walk-Forward Model Birleştirme [P0-02]
**Sorun:** Backtest hardcoded ELO+Poisson, live production GBM ensemble.  
**Fix:** walk_forward.py içinde de `model_birlestir()` kullan VEYA açıkça "ELO+Poisson baseline" olarak etiketle.  
**Teknik karar:** Backtest'te GBM kullanmak için GBM'in o fold zamanına kadar eğitilmesi gerekiyor — bu büyük refactor. Kısa vadede: walk_forward "ELO_POISSON_BASELINE" olarak etiketlensin, "ML Ensemble" iddiası kaldırılsın.

---

## FAZ 7 — TRUE WALK-FORWARD EĞİTİMİ

### Fix 7.1: Walk-Forward'da Fold-Local Calibration [P1-03]
**Sorun:** Her fold global calibrator.pkl kullanıyor.  
**Fix:** Her fold kendi kalibrasyonunu eğitecek şekilde refactor.

---

## FAZ 8 — FOLD-LOCAL CALIBRATION ✅ FAZ 7'DE KAPSANIYOR

---

## FAZ 9 — CANONICAL MARKET FAIR PROBABILITY

### Fix 9.1: Edge Formülü Tekleştirme [P0-08]
**Sorun:** 3 farklı edge formülü.  
**Fix:** `value/value_engine.py` oluştur. Tüm edge hesabı buradan.  
```python
calculate_market_fair_probability(odds_h, odds_d, odds_a)  # vig-normalized
calculate_model_market_edge(p_model, fair_p)
calculate_expected_value(p_model, odds)
```
main.py bu fonksiyonları kullanacak.

---

## FAZ 10 — CANONICAL EDGE/EV ENGINE ✅ FAZ 9'DA KAPSANIYOR

---

## FAZ 11 — SHARP/MARKET MOVEMENT AUDIT

### Fix 11.1: Sharp Claim Yeniden Etiketleme
**Sorun:** "Sharp Money" iddiası — sadece odds movement heuristic.  
**Fix:** Değişken isimlerini `MARKET_MOVEMENT_SIGNAL` olarak güncelle. "Sharp" sadece verified Pinnacle movement için.

---

## FAZ 12 — GOAL MARKETS SEPARATION

### Fix 12.1: 1X2 vs O/U vs BTTS Ayrımı
**Sorun:** Farklı market tipler aynı edge sistemiyle değerlendiriliyor.  
**Fix:** Her market için ayrı probability model ve ayrı edge threshold dökümantasyonu.

---

## FAZ 13 — CLV ENGINE

### Fix 13.1: Yanlış Closing Odds Kullanımı [P0-01]
**Sorun:** main.py L1026-1079 odds_cache.json'ı closing diye kullanıyor.  
**Fix:** Bu bloğu tamamen kaldır. CLV ancak `closing_odds.py`'dan gelen gerçek pre-kickoff snapshot'tan hesaplansın.  
**Test:** Closing odds timestamp > kickoff → reject.

---

## FAZ 14 — CLOSING ODDS COLLECTION

### Fix 14.1: Closing Window Kickoff Sonrası Engelle [P0-12]
**Sorun:** `CLOSING_CUTOFF_H = -0.5` kickoff sonrası 30dk hâlâ "closing".  
**Fix:** `CLOSING_CUTOFF_H = 0` — kickoff zamanı veya öncesi.

---

## FAZ 15 — SETTLEMENT + FIXTURE MATCHING

---

## FAZ 16 — RISK / BANKROLL / KELLY

### Fix 16.1: Bankroll Tekleştirme [P0-10]
**Sorun:** 4 farklı bankroll değeri (1000, 5000 karışımı).  
**Fix:** Tüm yerler `config/settings.py::BANKROLL_BASLANGIC` veya `risk/bankroll.py::get_current_bankroll()` kullanacak.  
main.py L804 hardcoded 1000.0 → `get_current_bankroll()` ile değiştir.

---

## FAZ 17 — PORTFOLIO OPTIMIZER

### Fix 17.1: Probability Field Bug [P0-09]
**Sorun:** `b.get("olasilik", 0.5)` — field yok, herkes 0.5 alıyor.  
**Fix:** `b.get("olasilik", b.get("p_secim", 0.5))` — doğru field name.  
**Test:** p_secim=0.7 olan bet olasilik=0.5 default almıyor.

---

## FAZ 18 — EXECUTION GATE / PAPER vs LIVE

### Fix 18.1: Gate Fail → Analysis Devam Ediyor
**Sorun:** Sharpe/CLV gate başarısız olsa da pipeline sinyal üretiyor.  
**Fix:** Execution blocked iken `execution_allowed=False` flag tüm output'a eklenmeli. Dashboard açıkça göstermeli.

---

## FAZ 19 — METRİKS ENGINE

### Fix 19.1: ROI Tanımı Düzelt
**Sorun:** `roi = total_pnl / initial_bankroll` — yanlış.  
**Fix:** `roi = total_pnl / total_staked` (yield). Ayrı metric: bankroll_return.

### Fix 19.2: Class Order Test [P1-01]
**Sorun:** walk_forward actual_int = HOME=2, DRAW=1, AWAY=0 ama model HOME=0, DRAW=1, AWAY=2.  
**Fix:** actual_int mapping düzelt.  
**Test:** Known outcome → known class index.

---

## FAZ 20 — REGRESSION + PROPERTY TESTS

### Yeni Test Listesi (eklenecekler):
1. `test_duplicate_pinnacle_fixture` — dedup
2. `test_wrong_day_matching` — +-1 gün reject
3. `test_no_b365_fallback` — Pinnacle yoksa reject
4. `test_xg_no_future` — cutoff sonrası veri etkisiz
5. `test_edge_consistent` — main.py = walk_forward.py aynı formül
6. `test_vig_normalization` — 3-way market fair prob sum to 1
7. `test_clv_no_current_cache` — odds_cache.json closing değil
8. `test_closing_before_kickoff` — kickoff sonrası reject
9. `test_bankroll_single_source` — tek kaynak
10. `test_portfolio_probability_field` — olasilik vs p_secim
11. `test_class_order_canonical` — HOME=0, DRAW=1, AWAY=2
12. `test_roi_formula` — total_pnl/total_staked
13. `test_walk_forward_model_label` — ELO_Poisson değil ML Ensemble

---

## FAZ 21 — GITHUB ACTIONS / CI

### Fix 21.1: Test Fail → Pipeline Dur
**Sorun:** pytest fail edince main.py yine çalışıyor.  
**Fix:** `set -e` veya `pytest ... || exit 1` ekle.

### Fix 21.2: || true Temizleme
**Sorun:** git komutlarında `|| true` critical error gizliyor.  
**Fix:** git hataları görünür olsun.

---

## FAZ 22 — REPORT REGENERATION
Mevcut markdown raporlar silinmeyecek — yeni kanonical metrik engine oluşturulacak.

---

## FAZ 23 — FINAL FULL-SYSTEM VALIDATION
Son adım. Tüm fix'lerden sonra:
1. compileall
2. Full pytest suite
3. Walk-forward backtest (etiketleri doğru)
4. Data quality audit
5. Leakage audit
6. CLAUDE_FINAL_AUDIT.md

---

## ÖNCELİK SIRASI

| Öncelik | Fix | Açıklama |
|---|---|---|
| **P0-1** | [P0-09] Portfolio probability bug | Hemen fix — 1 satır |
| **P0-2** | [P0-10] Bankroll tekleştirme | Hemen fix — birkaç satır |
| **P0-3** | [P0-01] CLV yanlış closing kaldır | main.py L1026-1079 sil |
| **P0-4** | [P0-05] Pinnacle fallback kaldır | walk_forward.py L89-107 |
| **P0-5** | [P0-06] +-1 gün matching kaldır | walk_forward.py L162-173 |
| **P0-6** | [P0-07] Pinnacle CSV dedup | load_pinnacle_historical_odds() |
| **P0-7** | [P0-11] 5-char matching kaldır | match_pinnacle_odds() |
| **P0-8** | [P0-04] xG future leakage | xg_proxy.py cutoff |
| **P0-9** | [P0-02] Backtest model label | walk_forward etiketi düzelt |
| **P0-10** | [P0-03] Global calibrator | fold-local calibration |
| **P0-11** | [P0-08] Edge formül tekleştir | value_engine.py |
| **P1-1** | [P1-01] Class order düzelt | actual_int mapping |
| **P1-2** | [P1-07] Model metadata ekle | pkl artifact metadata |
| **P2-1** | [P2-02] silent except kaldır | hata yönetimi |
| **P2-2** | [P2-03] GitHub Actions fail-fast | CI fix |

---

## TEMEL BAŞARI KRİTERİ

Sistem sonunda ille de pozitif ROI çıkarmak zorunda değil.

**GERÇEK BAŞARI:**
"Modelin ne bildiğini, marketten ne kadar farklı olduğunu, hangi verinin güvenilir olduğunu ve hangi koşulda bahis yapılmaması gerektiğini DOĞRU ölçen bir sistem."

Final test sonucu negatifse:
```
VERDICT: NO LIVE BETTING — INSUFFICIENT EVIDENCE
MODEL DOES NOT BEAT MARKET (out-of-sample)
```
Bu başarısızlık değil, dürüstlük.
