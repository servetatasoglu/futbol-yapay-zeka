# CLAUDE BASELINE AUDIT
**Repository:** futbol-yapay-zeka-main  
**Audit Tarihi:** 2026-10-07  
**Test Suite:** 47/47 PASSED (40.21s)

---

## A. Repository Dosya Ağacı (özet)

```
main.py (1119 satır) — çok şişkin orchestrator
backtesting/walk_forward.py (593 satır)
calibration/calibration.py, isotonic_calibrator.py, lig_kalibrasyon.py
config/settings.py (356 satır)
data/
  maclar.json (15.9MB), gbm_model.pkl (1.8MB), goals_model.pkl (8.6MB)
  calibrator.pkl (1.4KB GLOBAL), kalibrasyon.pkl (680B — ikinci artifact)
  xg_proxy_cache.json (19KB), clv_bet_log.json (12KB)
  pinnacle_odds/ (39 CSV: 2223-2425 + sezon etiketsiz kopyalar + parantezli kopyalar)
  odds.py (996 satır), matcher.py (708 satır), xg_proxy.py, closing_odds.py
features/ elo.py, rolling_features.py, team_stats.py, poisson.py ...
model/ ensemble.py (587 satır), train.py (838 satır), meta_learner.py
risk/ bankroll.py, portfolio_optimizer.py, adaptive_kelly.py
tracking/ clv_tracker.py, clv_engine.py
value/ edge.py (912 satır), analiz.py
tests/ (3 dosya, 47 test)
.github/workflows/daily_run.yml
25+ markdown rapor dosyası
```

---

## B. KRİTİK BULGULAR

### P0 — DATA LEAKAGE / WRONG ODDS / WRONG CLV / WRONG RISK

**[P0-01] CLV TAMAMEN YANLIŞ**
main.py L1026-1079: Kapanış oranı olarak bugünkü `odds_cache.json`'ı kullanıyor.
Bu live odds, pre-kickoff kapanış değil. Tüm CLV sayıları anlamsız.

**[P0-02] BACKTEST MODEL ≠ LIVE MODEL**  
walk_forward.py L345-349:
```python
raw_home = 0.55 * p_home_elo + 0.45 * (ph / tot_p)  # hardcoded ELO+Poisson
```
main.py → model_birlestir() → GBM + ELO + Poisson ensemble kullanıyor.
Backtest "ML Ensemble" demiyor ama raporlar öyle gösteriyor.

**[P0-03] GLOBAL CALIBRATör LEAKAGE**  
Her fold walk_forward'da aynı `data/calibrator.pkl` kullanılıyor.
Bu kalibratör tüm tarihe bakarak eğitilmişse erken fold'lara gelecek bilgisi sızıyor.

**[P0-04] xG FUTURE LEAKAGE**  
`xg_proxy.py::_dixon_coles_hesapla()`:
```python
bugun = datetime.utcnow()   # BUGÜNKÜ TARİH
sinir = (bugun - timedelta(days=3*365))  # Son 3 yıl — gelecek dahil
```
xG proxy cache bugünkü tarih baz alınarak tüm geçmiş+güncel veriden hesaplanıyor.
2023 maçının feature'ı için 2024-2025 sonuçları kullanılıyor.

**[P0-05] PINNACLE FALLBACK YANLIŞ ETİKETLENİYOR**  
walk_forward.py L89-107:
```python
if psh <= 1.0:
    psh = float(row.get("AvgH", 0) or row.get("B365H", 0) or 0)  # B365 → Pinnacle gibi
```
Pinnacle yoksa B365/Avg alıp yine "real_pinnacle" diye raporluyor.

**[P0-06] +-1 GÜN EŞLEŞMESİ**  
walk_forward.py L162-173: Aynı takımlar farklı günlerde oynamışsa yanlış maça eşleşme.

**[P0-07] DUPLICATE PINNACLE CSV'LER**  
`D1.csv` = `2425_D1.csv`, `D1(1).csv` = `2324_D1.csv` — aynı fixture iki kez.
load_pinnacle_historical_odds() dedup yapmıyor, sıralamaya bağlı.

**[P0-08] EDGE FORMÜLÜ TUTARSIZLIĞI — 3 FARKLI FORMÜL**
- main.py: `edge = p_model - (1/odds)` (raw implied, vig dahil)  
- walk_forward.py: `edge = p_mod - fair_p` (vig-normalized — doğru)  
- value/edge.py: ayrı kalibrasyon katmanlı  
Backtest pozitif edge gösterirken live negatif sonuç verebilir.

**[P0-09] PORTFOLIO OPTIMIZER PROBABILITY BUG**  
portfolio_optimizer.py:
```python
_ev_hesapla(b.get("olasilik", 0.5), ...)  # "olasilik" field yok!
```
Candidate bet objelerinde `p_secim` var, `olasilik` yok.
Optimizer herkes için 0.5 probability kullanıyor → EV hesabı yanlış.

**[P0-10] BANKROLL TUTARSIZLIĞI**  
- `config/settings.py`: BANKROLL_BASLANGIC = 5000  
- `risk/bankroll.py`: BASLANGIC_KASA = 5000.0  
- `main.py` L804: `bankroll = 1000.0` (hardcoded)  
- `walk_forward.py` default: `initial_bankroll=1000.0`  
- `portfolio_optimizer` çağrısı: `bankroll=1000.0`  
4 farklı değer. Yanlış bankroll → yanlış Kelly → yanlış stake.

**[P0-11] TEAM MATCHING: SUBSTRING + 5 KARAKTER**  
walk_forward.py L159:
```python
if (ch in ev_c or ev_c in ch or ch[:5] == ev_c[:5])  # 5 karakter eşleşme!
```
"Paris" = "Parma" gibi yanlış eşleşmeler mümkün.

**[P0-12] CLOSING WINDOW KICKOFF SONRASI**  
closing_odds.py L36:
```python
CLOSING_CUTOFF_H = -0.5  # 30 dakika SONRA bile "closing" kabul ediyor
```
In-play odds closing olarak alınabilir.

---

### P1 — MODEL VALIDATION / CALIBRATION / EDGE

**[P1-01] CLASS ORDER KARIŞIKLIĞI RİSKİ**  
walk_forward.py L310-312:
```python
actual_vector = [1.0 if actual_outcome == "AWAY" else 0.0,
                 1.0 if actual_outcome == "DRAW" else 0.0,  
                 1.0 if actual_outcome == "HOME" else 0.0]
# actual_int = 2 if HOME, 1 if DRAW, 0 if AWAY
```
Ama model: `SINIF_ESLESTIRME = {0: "1", 1: "X", 2: "2"}`  
= HOME=0, DRAW=1, AWAY=2  
vs backtest: HOME=2, DRAW=1, AWAY=0  
**GERÇEKLEŞTİ: actual_int tanımı ters!** Model [AWAY,DRAW,HOME] vector'ü tahmin ederken actual_int [HOME=2,DRAW=1,AWAY=0] → metrikler yanlış hesaplanıyor.

**[P1-02] BERABERLIK OLASILIĞI ÇÖKÜYOR**  
walk_forward.py Poisson tahmininde draw olasılığı çok düşük:
```python
p_draw_elo = 0.27 * math.exp(-denge * 1.2)  # Zayıf beraberlik modeli
```
DRAW sadece `p_draw_m > fair_d + 0.03` durumunda candidate oluyor.

**[P1-03] GLOBAL CALIBRATOR — FOLD-LOCAL DEĞİL**  
Walk-forward her fold için fold-local calibrator eğitmiyor.
Global calibrator olası future leakage içeriyor.

**[P1-04] SENTETIK STATS ÜRETIMI**  
model/ensemble.py L209-219: Takım verisi yoksa `sentetik_stats_uret()` çağırıyor.
Bu production'da veri_kaynak="TAM" yazıyor ama veri sentetik.

**[P1-05] DRAW EDGE EŞİĞİ MANÜEL**  
main.py L620-621: `min_edge *= 1.5` beraberlik için elle çarpılıyor.
Bu validation set sonucuna göre ayarlandı mı bilinmiyor.

**[P1-06] ARBİTRER SHARP BONUS'LAR**  
main.py L632: `{"ELITE": 1.40, "STRONG": 1.20}` bet_score çarpanları.
Data-driven kanıt yok. Validation set'e göre seçildi mi bilinmiyor.

**[P1-07] MODEL METADATA YOK**  
gbm_model.pkl içinde training_start/end, feature_version, git_commit, random_seed YOK.
Hangi veriyle ne zaman eğitildiği bilinmiyor.

---

### P2 — ARCHİTECTURE / MONİTORİNG

**[P2-01] MAIN.PY ÇOK ŞİŞKİN**  
1119 satır, 8+ farklı sorumluluğu var. Bakımı imkânsız.

**[P2-02] EXCEPT EXCEPTION: PASS PATTERN'LERİ**  
main.py L461: `except Exception: pass` — kalibrasyonda sessiz hata yutma.
Birçok yerde benzer silent fallback.

**[P2-03] GITHUB ACTIONS TEST FAİL → PRODUCTION DEVAM**  
`pytest` fail etse bile `main.py` çalışıyor. `fail-fast` explicit değil.
`|| true` yok ama test step sonrası step'ler koşulsuz çalışıyor.

**[P2-04] GIT PUSH LOOP RİSKİ**  
daily_run.yml: `git push` yaptıktan sonra `[skip ci]` commit mesajıyla loop engelleniyor.
Ama `skip ci` garantili değil tüm GitHub versiyonlarında.

**[P2-05] HAREKET_GUCU / SHARP_TİER DEĞİŞKEN ANLAM KARIŞIKLIĞI**  
`sharp_sinyal` = "EV" / "DEP" / "BER" / "YOK" — hem raw API hem de derived değer olarak kullanılıyor.

**[P2-06] VERİ KAYNAK DURUMU "TAM" YANLIŞ**  
main.py L224: `veri_kaynak = "TAM"` — sonra sentetik stats ekleniyor ama etiket değişmiyor.

---

### P3 — CLEANUP / OPTİMİZASYON

**[P3-01] DUPLICATE RAPORLAR**  
25+ markdown rapor dosyası — birbirinden çelişen sonuçlar içeriyor.

**[P3-02] DEBUG PRINT KALMIS**  
main.py L268: `print(f"DEBUG_TAHMIN {ev_ham}: ou_btts={ou_btts}")` — production'da bırakılmış.

**[P3-03] OBSOLETE WHITELIST**  
main.py L176-197: Static takım whitelistleri. Sezon değişince eskiyor.

**[P3-04] İKİ KALIBRATOR ARTIFACT**  
`data/calibrator.pkl` (1.4KB) ve `data/kalibrasyon.pkl` (680B). Hangisi kullanılıyor belirsiz.

**[P3-05] OPSİYONEL MODÜLLER ZİNCİRİ**  
ensemble.py'de 10+ `try/except ImportError` — hangi modülün aktif olduğu runtime'da belli oluyor, statik analiz imkânsız.

---

## ÖNEMLİ METRIK SORUNLARI

### ROI Hesabı Yanlış
walk_forward.py L498: `roi = (total_pnl / initial_bankroll) * 100.0`  
Bu ROI değil, absolute return on initial bankroll.  
Standart ROI: `total_pnl / total_staked`

### Sharpe Daily Returns Problemi  
walk_forward.py L448: `daily_returns[m_date[:10]] += pnl / max(bankroll, 1.0)`  
Her bahis için farklı bankroll denominator kullanıyor. Sharpe hesabı tutarsız.

### CLV Formülü Doğru Ama Yanlış Veri
`clv = (odds / cl_odds) - 1.0` — formül doğru.
Ama cl_odds = live odds cache, gerçek closing değil.

---

## MEVCUT RAPORLARIN OTORİTE STATÜSÜNDEKİ DURUMU

| Rapor | Güvenilirlik | Sebep |
|---|---|---|
| BACKTEST_REPORT.md | DÜŞÜK | Backtest ≠ production model |
| CLV_VALIDATION.md | DÜŞÜK | CLV yanlış closing odds |
| PRODUCTION_READINESS.md | DÜŞÜK | P0 sorunlar hâlâ var |
| LEAKAGE_FINAL_AUDIT.md | ORTA | xG leakage gözden kaçmış |
| DATA_QUALITY_REPORT.md | ORTA | Pinnacle duplicate tespiti yok |
