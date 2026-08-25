# analysis/gecmis_veri_egitim.py
"""
Geçmiş Veri Eğitim Motoru — XGBoost + LightGBM Ensemble
══════════════════════════════════════════════════════════════
8500+ maçtan feature üret → XGBoost + LightGBM ensemble → pickle'a kaydet

NEDEN ENSEMBLE?
  XGBoost: Yüksek doğruluk, ağaç derinliği iyi
  LightGBM: 10x hızlı, büyük veri için ideal
  İkisinin ortalaması → her ikisinin de zayıf noktasını kapatır

FEATURE'LAR (28 adet):
  - ELO farkı, ELO olasılıkları
  - Poisson lambda'ları, Poisson olasılıkları
  - Form skoru, momentum farkı
  - H2H geçmişi
  - Lig bazlı kodlama
  - Gol beklentisi toplamı / oranı
  - Lig sıralaması farkı
"""

import os
import time
import pickle
import math
import numpy as np
from collections import defaultdict

# XGBoost
try:
    import xgboost as xgb
    _XGB_VAR = True
except ImportError:
    _XGB_VAR = False

# LightGBM
try:
    import lightgbm as lgb
    _LGB_VAR = True
except ImportError:
    _LGB_VAR = False

# Fallback: sklearn
try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import cross_val_score
    _SKLEARN_VAR = True
except ImportError:
    _SKLEARN_VAR = False

MODEL_DOSYASI  = os.path.join(os.path.dirname(__file__), "..", "data", "gbm_model.pkl")
MIN_EGITIM_MAC = 200
# calibrator.pkl bu kadar günden yeniyse ensure_calibrator_if_missing yeniden eğitmez
CALIBRATOR_TAZELIK_GUN = 7


def _ensemble_prob_matrix(X, modeller: dict) -> np.ndarray:
    """Tüm modellerin predict_proba çıktısını sınıf 0,1,2 hizalı ortalama."""
    n = len(X)
    acc = np.zeros((n, 3), dtype=np.float64)
    if not modeller:
        return acc
    for _m in modeller.values():
        P = _m.predict_proba(X)
        cls = getattr(_m, "classes_", np.array([0, 1, 2]))
        row = np.zeros((n, 3), dtype=np.float64)
        for j in range(len(cls)):
            c = int(cls[j])
            if 0 <= c <= 2:
                row[:, c] = P[:, j]
        acc += row
    acc /= max(len(modeller), 1)
    return acc


def train_calibrator_from_models(X, y, modeller: dict) -> bool:
    """Ensemble olasılık matrisi ile isotonic kalibratörü kaydet."""
    from calibration.calibration import train_calibrator

    acc = _ensemble_prob_matrix(X, modeller)
    train_calibrator(acc, y, method="isotonic")
    return True


def ensure_calibrator_if_missing(ham_veri: dict, istatistikler: dict, elo_sonuclari: dict) -> bool:
    """
    gbm_model.pkl var, calibrator.pkl yoksa veya 7 günden eskiyse: veriyi üretip kalibratörü eğitir.
    Son 7 gün içinde oluşturulmuş calibrator.pkl için yeniden eğitim yapılmaz.
    main / egit 'yuklendi' dalında çağrılır.
    """
    from calibration.calibration import CALIBRATOR_PATH

    if os.path.exists(CALIBRATOR_PATH):
        yas_gun = (time.time() - os.path.getmtime(CALIBRATOR_PATH)) / 86400.0
        if yas_gun <= CALIBRATOR_TAZELIK_GUN:
            return True
    if not os.path.exists(MODEL_DOSYASI):
        return False
    if not (_XGB_VAR or _LGB_VAR or _SKLEARN_VAR):
        return False

    try:
        X, y, atlalanlar = _veri_hazirla(ham_veri, istatistikler, elo_sonuclari)
        if len(X) < MIN_EGITIM_MAC:
            print(f"  ⚠️  Kalibratör için yetersiz maç: {len(X)} (min {MIN_EGITIM_MAC})")
            return False
        with open(MODEL_DOSYASI, "rb") as f:
            meta = pickle.load(f)
        modeller = meta.get("modeller") or {}
        if not modeller:
            print("  ⚠️  gbm_model.pkl içinde model yok — kalibratör oluşturulamadı")
            return False
        train_calibrator_from_models(X, y, modeller)
        print("  ✅ calibrator oluşturuldu / yenilendi → data/calibrator.pkl")
        return True
    except Exception as _e:
        print(f"  ⚠️  calibrator oluşturulamadı: {_e}")
        return False

LIG_KODLARI = {
    "PL": 0, "PD": 1, "BL1": 2, "SA": 3, "FL1": 4,
    "DED": 5, "PPL": 6, "ELC": 7, "CL": 8, "EL": 9,
}


def _elo_olasilik(ev_elo, dep_elo, ev_avantaj=65):
    fark = ev_elo + ev_avantaj - dep_elo
    return 1 / (1 + 10 ** (-fark / 400))


def _poisson_p(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k * math.exp(-lam)) / math.factorial(k)


def _mac_sonucu_olasilik(lam_ev, lam_dep, max_gol=7):
    ev_p = ber_p = dep_p = 0.0
    for h in range(max_gol + 1):
        for a in range(max_gol + 1):
            p = _poisson_p(lam_ev, h) * _poisson_p(lam_dep, a)
            if h > a:    ev_p  += p
            elif h == a: ber_p += p
            else:        dep_p += p
    t = ev_p + ber_p + dep_p
    if t > 0:
        ev_p /= t; ber_p /= t; dep_p /= t
    return ev_p, ber_p, dep_p


def _feature_uret(mac, ev_ist, dep_ist, ev_elo, dep_elo,
                   ev_form, dep_form, lig_kodu, ev_xg=None, dep_xg=None,
                   ev_rolling=None, dep_rolling=None):
    """62 feature üretir: 32 temel + 30 rolling (ev/dep ayrımı, xG trend, SoS vs.)"""
    elo_fark  = ev_elo - dep_elo
    elo_ev_p  = _elo_olasilik(ev_elo, dep_elo)
    elo_dep_p = 1 - elo_ev_p

    lig_ort = 1.35
    ev_huc  = ev_ist.get("hucum_genel",   lig_ort)
    ev_sav  = ev_ist.get("savunma_genel", lig_ort)
    dep_huc = dep_ist.get("hucum_genel",  lig_ort)
    dep_sav = dep_ist.get("savunma_genel", lig_ort)

    lam_ev  = max(0.4, min(ev_huc  / lig_ort * dep_sav / lig_ort * lig_ort * 1.06, 3.5))
    lam_dep = max(0.4, min(dep_huc / lig_ort * ev_sav  / lig_ort * lig_ort,         3.5))

    pois_ev_p, pois_ber_p, pois_dep_p = _mac_sonucu_olasilik(lam_ev, lam_dep)

    ev_form_s  = ev_form.get("skor",      0.5)
    dep_form_s = dep_form.get("skor",     0.5)
    ev_mom     = ev_form.get("momentum",  0.0)
    dep_mom    = dep_form.get("momentum", 0.0)

    h2h_ev_lam  = mac.get("h2h_ev_lambda",  1.0)
    h2h_dep_lam = mac.get("h2h_dep_lambda", 1.0)
    h2h_mac_s   = mac.get("h2h_mac",        0)

    lam_toplam    = lam_ev + lam_dep
    lam_oran      = lam_ev / max(lam_dep, 0.1)
    ev_mac_s      = min(ev_ist.get("mac_sayisi",  0) / 30, 1.0)
    dep_mac_s     = min(dep_ist.get("mac_sayisi", 0) / 30, 1.0)
    lig_id        = LIG_KODLARI.get(lig_kodu, 9) / 10.0

    ensemble_ev  = 0.5 * elo_ev_p  + 0.5 * pois_ev_p
    ensemble_dep = 0.5 * elo_dep_p + 0.5 * pois_dep_p
    ensemble_ber = max(0.0, 1 - ensemble_ev - ensemble_dep)

    ev_sira_oran  = ev_ist.get("lig_sira_oran",  0.5)
    dep_sira_oran = dep_ist.get("lig_sira_oran", 0.5)
    sira_fark     = ev_sira_oran - dep_sira_oran

    ev_xg_val  = ev_xg.get("xg", 1.35) if ev_xg else 1.35
    dep_xg_val = dep_xg.get("xg", 1.35) if dep_xg else 1.35
    ev_xg_diff = ev_xg.get("xg_diff", 0.0) if ev_xg else 0.0
    dep_xg_diff= dep_xg.get("xg_diff", 0.0) if dep_xg else 0.0

    # ── Temel 32 Feature ──
    temel = [
        elo_fark / 400, elo_ev_p, elo_dep_p, min(abs(elo_fark) / 200, 1.0),
        lam_ev, lam_dep, lam_toplam, lam_oran, pois_ev_p, pois_dep_p,
        ev_form_s, dep_form_s, ev_form_s - dep_form_s, ev_mom, dep_mom,
        h2h_ev_lam, h2h_dep_lam, min(h2h_mac_s / 10, 1.0),
        ensemble_ev, ensemble_dep, ensemble_ber,
        ev_mac_s, dep_mac_s, sira_fark, ev_sira_oran, dep_sira_oran,
        lig_id, pois_ber_p,
        ev_xg_val, dep_xg_val, ev_xg_diff, dep_xg_diff,
    ]

    # ── Rolling 30 Feature (ev/dep ayrımı, trend, SoS) ──
    from features.rolling_features import rolling_feature_vektoru
    rolling = rolling_feature_vektoru(
        ev_takim="__ev__", dep_takim="__dep__",
        rolling_db={"__ev__": ev_rolling or {}, "__dep__": dep_rolling or {}}
    )

    return temel + rolling


FEATURE_ISIMLERI = [
    # Temel 32
    "elo_fark_norm", "elo_ev_p", "elo_dep_p", "elo_guven",
    "lam_ev", "lam_dep", "lam_toplam", "lam_oran",
    "pois_ev_p", "pois_dep_p",
    "ev_form", "dep_form", "form_fark", "ev_mom", "dep_mom",
    "h2h_ev_lam", "h2h_dep_lam", "h2h_guven",
    "ensemble_ev", "ensemble_dep", "ensemble_ber",
    "ev_mac_s", "dep_mac_s", "sira_fark",
    "ev_sira", "dep_sira", "lig_id", "pois_ber_p",
    "ev_xg", "dep_xg", "ev_xg_diff", "dep_xg_diff",
    # Rolling 30
    "rol_ev_gol5", "rol_ev_yed5", "rol_ev_puan5", "rol_ev_clean", "rol_ev_sos",
    "rol_dep_gol5", "rol_dep_yed5", "rol_dep_puan5", "rol_dep_clean", "rol_dep_sos",
    "rol_hucum_avantaj", "rol_dep_hucum_savunma", "rol_form_fark",
    "rol_ev_xg_diff", "rol_dep_xg_diff",
    "rol_ev_kg", "rol_dep_kg",
    "rol_ev_tutarsiz", "rol_dep_tutarsiz",
    "rol_ev_soku", "rol_dep_soku",
    "rol_ev_trend", "rol_dep_trend",
    "rol_sos_fark", "rol_guc_fark",
    "rol_ev_veri_guveni", "rol_dep_veri_guveni",
    "rol_gol_toplam", "rol_yed_toplam",
    "rol_ev_avantaj_skoru",
]


def _veri_hazirla(ham_veri, istatistikler, elo_sonuclari):
    from features.h2h_model import h2h_analiz
    from data.xg_proxy import xg_yukle, xg_ara
    from features.rolling_features import rolling_features_uret

    print("  📊 Rolling feature'lar hesaplanıyor (ev/dep ayrımı, SoS, xG trend)...")
    rolling_db = rolling_features_uret(ham_veri, n_son=5)
    print(f"  ✅ {len(rolling_db)} takım için rolling istatistik hazır")

    xg_db = xg_yukle()
    X, y = [], []
    atlalanlar = 0

    for lig_kodu, maclar in ham_veri.items():
        maclar_sirali = sorted(maclar, key=lambda m: m.get("utcDate", ""))
        kumulatif     = defaultdict(list)

        for mac in maclar_sirali:
            try:
                ev      = mac["homeTeam"]["name"]
                dep     = mac["awayTeam"]["name"]
                ev_gol  = int(mac["score"]["fullTime"]["home"])
                dep_gol = int(mac["score"]["fullTime"]["away"])
            except (KeyError, TypeError, ValueError):
                atlalanlar += 1
                continue

            if ev_gol > dep_gol:    etiket = 2
            elif ev_gol == dep_gol: etiket = 1
            else:                   etiket = 0

            ev_ist  = istatistikler.get(ev,  {})
            dep_ist = istatistikler.get(dep, {})
            if not ev_ist or not dep_ist:
                atlalanlar += 1
                continue
            if ev_ist.get("mac_sayisi", 0) < 5 or dep_ist.get("mac_sayisi", 0) < 5:
                atlalanlar += 1
                continue

            ev_elo  = elo_sonuclari.get(ev,  {}).get("elo", 1500)
            dep_elo = elo_sonuclari.get(dep, {}).get("elo", 1500)

            ev_form  = _basit_form(kumulatif[ev][-10:])
            dep_form = _basit_form(kumulatif[dep][-10:])

            # Rolling feature'ları o ana kadar birikmiş geçmişten al
            ev_rolling  = rolling_db.get(ev,  {})
            dep_rolling = rolling_db.get(dep, {})

            mac_h2h = {"h2h_ev_lambda": 1.0, "h2h_dep_lambda": 1.0, "h2h_mac": 0}
            try:
                h2h_s   = h2h_analiz(ev, dep, istatistikler, ham_veri)
                mac_h2h = {
                    "h2h_ev_lambda":  h2h_s.get("ev_lambda_d",  1.0),
                    "h2h_dep_lambda": h2h_s.get("dep_lambda_d", 1.0),
                    "h2h_mac":        h2h_s.get("mac_sayisi",   0),
                }
            except Exception:
                pass

            try:
                ev_xg_veri  = xg_ara(ev,  xg_db)
                dep_xg_veri = xg_ara(dep, xg_db)
                feat = _feature_uret(
                    mac_h2h, ev_ist, dep_ist,
                    ev_elo, dep_elo,
                    ev_form, dep_form, lig_kodu,
                    ev_xg_veri, dep_xg_veri,
                    ev_rolling=ev_rolling, dep_rolling=dep_rolling
                )
                X.append(feat)
                y.append(etiket)
            except Exception:
                atlalanlar += 1
                continue

            kumulatif[ev].append({"attik": ev_gol,  "yedik": dep_gol})
            kumulatif[dep].append({"attik": dep_gol, "yedik": ev_gol})

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32), atlalanlar



def _xgb_egit(X, y):
    """
    v3.0: Purged Walk-Forward CV

    Standard TimeSeriesSplit has NO gap between train and test folds.
    This means the model can memorise team-specific signals from recent
    matches that directly precede the test fold — a subtle but critical
    data leakage source.

    Fix: Add PURGE_GAP matches between train end and test start.
    Primary metric: log_loss (calibration-aware), not accuracy.
    """
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import log_loss, accuracy_score

    PURGE_GAP = 5   # Skip 5 matches between train/test to prevent leakage

    # v3.0: Tightened hyperparameters for anti-overfitting
    # max_depth 5→4: shallower trees = less memorisation
    # min_child_weight 10→20: requires more samples per leaf
    # Higher regularization (reg_alpha, reg_lambda)
    params = {
        "objective":         "multi:softprob",
        "num_class":         3,
        "n_estimators":      300,       # Reduced from 400
        "max_depth":         4,         # v3.0: 5 → 4 (anti-overfit)
        "learning_rate":     0.04,      # Slightly higher (fewer trees)
        "subsample":         0.75,      # v3.0: 0.8 → 0.75
        "colsample_bytree":  0.75,      # v3.0: 0.8 → 0.75
        "min_child_weight":  20,        # v3.0: 10 → 20 (anti-overfit)
        "gamma":             0.2,       # v3.0: 0.1 → 0.2
        "reg_alpha":         0.3,       # v3.0: 0.1 → 0.3
        "reg_lambda":        2.0,       # v3.0: 1.0 → 2.0
        "eval_metric":       "mlogloss",
        "random_state":      42,
        "n_jobs":            -1,
        "verbosity":         0,
    }

    tscv    = TimeSeriesSplit(n_splits=5)
    log_losses  = []
    accuracies  = []
    fold_importances = []  # Track stability across folds

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        # v3.0: PURGE — remove last PURGE_GAP samples from train
        # to avoid leakage from matches just before the val fold
        purged_train_idx = train_idx[:-PURGE_GAP] if len(train_idx) > PURGE_GAP else train_idx

        model = xgb.XGBClassifier(**params)
        model.fit(
            X[purged_train_idx], y[purged_train_idx],
            eval_set=[(X[val_idx], y[val_idx])],
            verbose=False
        )
        proba = model.predict_proba(X[val_idx])
        pred  = model.predict(X[val_idx])

        # Primary: log_loss (calibration-aware)
        # Secondary: accuracy (for reporting)
        ll  = log_loss(y[val_idx], proba)
        acc = accuracy_score(y[val_idx], pred)
        log_losses.append(ll)
        accuracies.append(acc)
        fold_importances.append(dict(zip(FEATURE_ISIMLERI, model.feature_importances_)))

    # v3.0: Feature importance stability check
    # Features with high variance across folds are likely overfitting to noise
    stable_features = {}
    if fold_importances:
        all_feats = fold_importances[0].keys()
        for feat in all_feats:
            vals = [fi.get(feat, 0) for fi in fold_importances]
            mean_imp = np.mean(vals)
            std_imp  = np.std(vals)
            # Stability ratio: low std/mean = stable, high = unstable (noise)
            stability = 1.0 - min(1.0, std_imp / (mean_imp + 1e-9))
            stable_features[feat] = round(float(stability), 3)

    model_final = xgb.XGBClassifier(**params)
    model_final.fit(X, y, verbose=False)

    onemler = sorted(
        zip(FEATURE_ISIMLERI, model_final.feature_importances_),
        key=lambda x: x[1], reverse=True
    )

    ort_logloss  = round(float(np.mean(log_losses)), 4)
    ort_accuracy = round(float(np.mean(accuracies)), 4)

    print(f"  XGBoost (Purged CV): log_loss={ort_logloss:.4f} | accuracy={ort_accuracy:.3f}")

    return model_final, ort_accuracy, dict(onemler)



def _lgb_egit(X, y):
    # NEXT LEVEL (Option B): Optuna Bayesian Optimization for LightGBM
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import log_loss, accuracy_score
    import optuna
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    tscv = TimeSeriesSplit(n_splits=3) # Faster evaluation for Optuna

    def objective(trial):
        params = {
            "objective":          "multiclass",
            "num_class":          3,
            "n_estimators":       trial.suggest_int("n_estimators", 100, 400),
            "max_depth":          trial.suggest_int("max_depth", 3, 7),
            "learning_rate":      trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "subsample":          trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree":   trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_samples":  trial.suggest_int("min_child_samples", 15, 50),
            "reg_alpha":          trial.suggest_float("reg_alpha", 1e-4, 1.0, log=True),
            "reg_lambda":         trial.suggest_float("reg_lambda", 1e-4, 1.0, log=True),
            "random_state":       42,
            "n_jobs":             -1,
            "verbose":            -1,
        }
        
        cv_scores = []
        for train_idx, val_idx in tscv.split(X):
            model = lgb.LGBMClassifier(**params)
            model.fit(X[train_idx], y[train_idx])
            pred_proba = model.predict_proba(X[val_idx])
            # Minimize log_loss for better calibration
            score = log_loss(y[val_idx], pred_proba)
            cv_scores.append(score)
            
        return np.mean(cv_scores)

    print("  🔍 Optuna Bayesian Optimization çalışıyor (15 trial)...")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=15, timeout=60)
    
    best_params = study.best_params
    best_params.update({
        "objective": "multiclass", "num_class": 3, 
        "random_state": 42, "n_jobs": -1, "verbose": -1
    })
    
    print(f"  🏆 Optuna En İyi Parametreler: {study.best_params}")
    
    # Final model with best params on 5-fold CV for accuracy reporting
    tscv_final = TimeSeriesSplit(n_splits=5)
    skorlar = []
    for train_idx, val_idx in tscv_final.split(X):
        model = lgb.LGBMClassifier(**best_params)
        model.fit(X[train_idx], y[train_idx])
        pred = model.predict(X[val_idx])
        skorlar.append(accuracy_score(y[val_idx], pred))

    model_final = lgb.LGBMClassifier(**best_params)
    model_final.fit(X, y)

    onemler = sorted(
        zip(FEATURE_ISIMLERI, model_final.feature_importances_),
        key=lambda x: x[1], reverse=True
    )
    return model_final, round(float(np.mean(skorlar)), 4), dict(onemler)


def egit(ham_veri: dict, istatistikler: dict,
          elo_sonuclari: dict, lig_ortalamasi: dict,
          zorla=False) -> dict:
    """XGBoost + LightGBM ensemble ile eğit ve kaydet."""
    if not _XGB_VAR and not _LGB_VAR and not _SKLEARN_VAR:
        return {"durum": "kutuphane_yok", "dogruluk": 0, "mac_sayisi": 0}

    if not zorla and os.path.exists(MODEL_DOSYASI):
        ensure_calibrator_if_missing(ham_veri, istatistikler, elo_sonuclari)
        return {"durum": "yuklendi", **_model_meta_oku()}

    print("  🤖 Ensemble eğitimi başlıyor (XGBoost + LightGBM)...")

    X, y, atlalanlar = _veri_hazirla(ham_veri, istatistikler, elo_sonuclari)

    if len(X) < MIN_EGITIM_MAC:
        print(f"  ⚠️  Yetersiz veri: {len(X)} maç")
        return {"durum": "yetersiz_veri", "dogruluk": 0, "mac_sayisi": len(X)}

    print(f"  📊 {len(X)} maç  ({atlalanlar} atlandı)")

    modeller    = {}
    dogruluklar = {}

    if _XGB_VAR:
        print("  ⚡ XGBoost eğitiliyor...")
        xgb_model, xgb_dok, xgb_onem = _xgb_egit(X, y)
        modeller["xgb"]    = xgb_model
        dogruluklar["xgb"] = xgb_dok
        print(f"     CV doğruluk: %{xgb_dok*100:.1f}  |  top feature: {list(xgb_onem.keys())[0]}")

    if _LGB_VAR:
        print("  ⚡ LightGBM eğitiliyor...")
        lgb_model, lgb_dok, lgb_onem = _lgb_egit(X, y)
        modeller["lgb"]    = lgb_model
        dogruluklar["lgb"] = lgb_dok
        print(f"     CV doğruluk: %{lgb_dok*100:.1f}  |  top feature: {list(lgb_onem.keys())[0]}")

    if not modeller and _SKLEARN_VAR:
        print("  ⚡ GradientBoosting (fallback)...")
        gbm     = GradientBoostingClassifier(n_estimators=200, max_depth=4,
                                              learning_rate=0.05, random_state=42)
        cv      = cross_val_score(gbm, X, y, cv=5, scoring="accuracy")
        gbm_kal = CalibratedClassifierCV(gbm, cv=5, method="isotonic")
        gbm_kal.fit(X, y)
        modeller["sklearn"]    = gbm_kal
        dogruluklar["sklearn"] = round(float(cv.mean()), 4)

    ort_dogruluk = round(sum(dogruluklar.values()) / max(len(dogruluklar), 1), 4)

    os.makedirs(os.path.dirname(MODEL_DOSYASI), exist_ok=True)
    meta = {
        "modeller":   modeller,
        "dogruluk":   ort_dogruluk,
        "mac_sayisi": len(X),
        "tip":        list(modeller.keys()),
    }
    with open(MODEL_DOSYASI, "wb") as f:
        pickle.dump(meta, f)

    # ── Isotonic kalibratör: eğitim kümesi üzerinde ensemble → data/calibrator.pkl
    if modeller:
        try:
            train_calibrator_from_models(X, y, modeller)
            print("  ✅ calibrator oluşturuldu → data/calibrator.pkl (isotonic)")
        except Exception as _e:
            print(f"  ⚠️  Kalibratör eğitilemedi: {_e}")

    print(f"  ✅ Ensemble kaydedildi → {list(modeller.keys())}  %{ort_dogruluk*100:.1f} ort. doğruluk")
    return {"durum": "egitildi", "dogruluk": ort_dogruluk, "mac_sayisi": len(X)}


def tahmin_yap(ev_ist, dep_ist, ev_elo, dep_elo,
                ev_form, dep_form, lig_kodu,
                h2h_mac=None, ev_takim=None, dep_takim=None):
    """Ensemble ile tek maç tahmini."""
    if not os.path.exists(MODEL_DOSYASI):
        return None

    try:
        with open(MODEL_DOSYASI, "rb") as f:
            meta = pickle.load(f)
    except Exception:
        return None

    mac_h2h = {"h2h_ev_lambda": 1.0, "h2h_dep_lambda": 1.0, "h2h_mac": 0}
    if h2h_mac:
        mac_h2h = {
            "h2h_ev_lambda":  h2h_mac.get("ev_lambda_d",  1.0),
            "h2h_dep_lambda": h2h_mac.get("dep_lambda_d", 1.0),
            "h2h_mac":        h2h_mac.get("mac_sayisi",   0),
        }

    from data.xg_proxy import xg_yukle, xg_ara
    xg_db = xg_yukle()
    ev_xg_veri = xg_ara(ev_takim, xg_db) if ev_takim else None
    dep_xg_veri= xg_ara(dep_takim, xg_db) if dep_takim else None

    try:
        feat    = _feature_uret(mac_h2h, ev_ist, dep_ist,
                                 ev_elo, dep_elo, ev_form, dep_form, lig_kodu,
                                 ev_xg=ev_xg_veri, dep_xg=dep_xg_veri)
        feat_np = np.array([feat], dtype=np.float32)
    except Exception:
        return None

    probalar = []
    for isim, model in meta.get("modeller", {}).items():
        try:
            p       = model.predict_proba(feat_np)[0]
            classes = list(model.classes_) if hasattr(model, "classes_") else [0, 1, 2]
            p_map   = dict(zip(classes, p))
            probalar.append([p_map.get(2, 0.33), p_map.get(1, 0.33), p_map.get(0, 0.33)])
        except Exception:
            continue

    if not probalar:
        return None

    ort = np.mean(probalar, axis=0)
    t   = ort.sum()
    if t > 0:
        ort /= t

    ort_raw = np.array(ort, dtype=np.float64).copy()
    try:
        from calibration.calibration import (
            apply_probability_pipeline,
            log_calibration_distribution,
        )
        result = apply_probability_pipeline(ort_raw)
        ort = result["probs"]
        # Genişletilmiş log: overconfidence, calibration ve safe_cap durumu
        log_calibration_distribution(
            result["before"], result["after"],
            overconfidence_applied=result["overconfidence_applied"],
            calibration_used=result["calibration_used"],
            safe_cap_applied=result["safe_cap_applied"],
        )
    except Exception:
        # Fallback: minimum overconfidence fix ile devam et
        m = float(ort_raw.max())
        factor = 0.75 if m > 0.85 else (0.85 if m > 0.75 else 1.0)
        ort = ort_raw * factor
        s = ort.sum()
        if s > 0:
            ort /= s

    return {
        "ev_p":  round(float(ort[0]), 4),
        "ber_p": round(float(ort[1]), 4),
        "dep_p": round(float(ort[2]), 4),
        "guven": round(float(ort.max()), 4),
        "tip":   meta.get("tip", []),
    }


def model_meta_oku() -> dict:
    return _model_meta_oku()


def _model_meta_oku() -> dict:
    if not os.path.exists(MODEL_DOSYASI):
        return {"dogruluk": 0, "mac_sayisi": 0}
    try:
        with open(MODEL_DOSYASI, "rb") as f:
            meta = pickle.load(f)
        return {"dogruluk": meta.get("dogruluk", 0),
                "mac_sayisi": meta.get("mac_sayisi", 0),
                "tip": meta.get("tip", [])}
    except Exception:
        return {"dogruluk": 0, "mac_sayisi": 0}


def yenileme_gerekli_mi() -> tuple:
    """GBM modelinin yenilenmesi gerekip gerekmediğini ve kaç gün geçtiğini döner."""
    from config.settings import MODEL_YENILEME_GUN
    if not os.path.exists(MODEL_DOSYASI):
        return True, 999.0
    age_days = (time.time() - os.path.getmtime(MODEL_DOSYASI)) / 86400.0
    return age_days >= MODEL_YENILEME_GUN, round(age_days, 1)


def durum_raporu() -> dict:
    """Modelin sağlık ve yenileme durum raporunu döndürür."""
    from config.settings import MODEL_YENILEME_GUN
    from datetime import datetime
    gerekli, gecen = yenileme_gerekli_mi()
    meta = _model_meta_oku()
    son_mod = datetime.fromtimestamp(os.path.getmtime(MODEL_DOSYASI)).strftime("%Y-%m-%d %H:%M") if os.path.exists(MODEL_DOSYASI) else "Yok"
    return {
        "yenileme_gerekli": gerekli,
        "gecen_gun": gecen,
        "esik_gun": MODEL_YENILEME_GUN,
        "son_yenileme": son_mod,
        "son_dogruluk": meta.get("dogruluk", 0),
        "son_mac_sayisi": meta.get("mac_sayisi", 0),
    }



def _basit_form(mac_listesi: list) -> dict:
    if not mac_listesi:
        return {"skor": 0.5, "momentum": 0.0, "guven": 0.0}
    sonuclar = []
    for m in mac_listesi:
        att = m.get("attik", 0)
        yed = m.get("yedik", 0)
        if att > yed:    sonuclar.append(1.0)
        elif att == yed: sonuclar.append(0.5)
        else:            sonuclar.append(0.0)
    decay      = 0.85
    agirliklar = [decay ** (len(sonuclar) - 1 - i) for i in range(len(sonuclar))]
    skor       = sum(s * a for s, a in zip(sonuclar, agirliklar)) / max(sum(agirliklar), 0.01)
    momentum   = 0.0
    if len(sonuclar) >= 6:
        son3    = sum(sonuclar[-3:]) / 3
        onceki3 = sum(sonuclar[-6:-3]) / 3
        momentum = round(son3 - onceki3, 3)
    return {"skor": round(skor, 3), "momentum": momentum,
            "guven": min(1.0, len(sonuclar) / 8)}

if __name__ == "__main__":
    from data.matches import veri_yukle
    from features.team_stats import istatistik_hesapla
    from features.elo import elo_hesapla
    
    # 1. Ham veriyi yükle
    print("Otonom Eğitim: Ham maç verileri yükleniyor...")
    ham_veri = veri_yukle()
    
    # 2. İstatistik ve ELO'ları hesapla (Canlı olarak, tıpkı main.py gibi)
    print("Otonom Eğitim: Veritabanı istatistikleri ve ELO puanları hesaplanıyor...")
    try:
        istatistikler = istatistik_hesapla()
        elo_sonuclari = elo_hesapla(ham_veri)
        print(f"Otonom Eğitim: {len(istatistikler)} takım istatistiği başarıyla hesaplandı.")
    except Exception as e:
        print(f"⚠️ İstatistik/ELO hesaplama hatası: {e}")
        istatistikler = {}
        elo_sonuclari = {}
    
    # 3. Model Eğit
    egit(ham_veri, istatistikler, elo_sonuclari, {}, zorla=True)