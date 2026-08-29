# analysis/calibration.py
# ── Quant Betting Engine – Probability Calibration Module ─────────────────────
# Pipeline sırası: raw → overconfidence_fix → calibrate (güvenilirse) → safe_cap → normalize
# ─────────────────────────────────────────────────────────────────────────────
import os
import json
import pickle
import time
from datetime import datetime, timezone

import numpy as np

try:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    _SKLEARN_VAR = True
except ImportError:
    _SKLEARN_VAR = False

CALIBRATOR_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "calibrator.pkl")
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
CAL_DIST_LOG = os.path.join(LOG_DIR, "calibration_distribution.jsonl")

# ── Güven parametreleri ───────────────────────────────────────────────────────
# Kalibrasyon bu değerden yüksek max-prob artışı gösterirse SKIP edilir
_CAL_AMPLIFICATION_THRESHOLD = 0.05   # kalibrasyon max-prob'u >5pp artırırsa güvenilmez
_CAL_MAX_AGE_DAYS = 30                # pkl bu kadar günden eskiyse skip
_CAL_MIN_EXPECTED_SAMPLES = 200       # pkl çok küçük veriyle üretildiyse skip (meta kontrolü)


class CalibrationError(RuntimeError):
    """Hard calibration failure — fallback is intentionally provided at pipeline level."""


# ─────────────────────────────────────────────────────────────────────────────
# 1. TRAIN
# ─────────────────────────────────────────────────────────────────────────────

def train_calibrator(X_probs, y_true, method="isotonic"):
    """
    X_probs: shape (n_samples, n_classes) — uncalibrated ensemble probs
    y_true : shape (n_samples,)           — integer class labels (0,1,2)

    One-vs-Rest isotonic/platt — kaydedilir: data/calibrator.pkl
    """
    if not _SKLEARN_VAR:
        raise CalibrationError("sklearn yok — isotonic kalibrasyon eğitilemez")

    calibrators = {}
    for c in range(X_probs.shape[1]):
        y_c = (y_true == c).astype(int)
        probe_c = X_probs[:, c]

        if method == "isotonic":
            cal = IsotonicRegression(out_of_bounds="clip")
            cal.fit(probe_c, y_c)
        elif method == "platt":
            cal = LogisticRegression()
            cal.fit(probe_c.reshape(-1, 1), y_c)
        else:
            raise ValueError("Bilinmeyen kalibrasyon metodu: " + method)

        calibrators[c] = {"model": cal, "method": method}

    os.makedirs(os.path.dirname(CALIBRATOR_PATH), exist_ok=True)
    with open(CALIBRATOR_PATH, "wb") as f:
        pickle.dump(calibrators, f)

    return calibrators


# ─────────────────────────────────────────────────────────────────────────────
# 2. OVERCONFIDENCE FIX  (tiered, güçlendirilmiş)
# ─────────────────────────────────────────────────────────────────────────────

def apply_overconfidence_fix(prob: float) -> float:
    """Tekil olasılık için overconfidence törpüleme (eski imza – backward compat)."""
    if prob > 0.85:
        return prob * 0.75
    if prob > 0.75:
        return prob * 0.85
    return prob


def _tiered_overconfidence_fix(probs: np.ndarray) -> np.ndarray:
    """
    Vektör bazlı overconfidence shrinkage (Uniform Priora Doğru Daraltma).
    Scalar çarpım yerine, ekstrem olasılıkları tekdüze dağılıma (1/K) doğru daraltır.
    
    - max > 0.85 → %25 uniform prior karışımı
    - max > 0.75 → %15 uniform prior karışımı
    """
    p = np.array(probs, dtype=np.float64).copy()
    m = float(p.max())
    k = float(len(p)) # 3 sınıflı için 3
    uniform = 1.0 / max(k, 1.0)
    
    if m > 0.85:
        # %25 uniform prior karışımı (agresif overconfidence önleme)
        p = 0.75 * p + 0.25 * uniform
    elif m > 0.75:
        # %15 uniform prior karışımı (orta düzey overconfidence önleme)
        p = 0.85 * p + 0.15 * uniform
    else:
        return p

    s = p.sum()
    return p / s if s > 1e-9 else p


# ─────────────────────────────────────────────────────────────────────────────
# 3. CALIBRATION TRUST GUARD
# ─────────────────────────────────────────────────────────────────────────────

def _is_calibration_trustworthy(probs_before: np.ndarray) -> bool:
    """
    calibrator.pkl'yi kullanmadan önce güvenilirlik kontrolü.
    False döndürürse apply_calibration çağrısı SKIP edilir.

    Kontroller:
      1. Dosya var mı?
      2. Çok eski mi? (> _CAL_MAX_AGE_DAYS)
      3. Dry-run: kalibre edilmiş max, raw max'ı _CAL_AMPLIFICATION_THRESHOLD kadar artırıyor mu?
         → artırıyorsa trustworthy=False
    """
    if not os.path.exists(CALIBRATOR_PATH):
        return False

    age = (time.time() - os.path.getmtime(CALIBRATOR_PATH)) / 86400.0
    if age > _CAL_MAX_AGE_DAYS:
        return False

    # Dry-run: kalibrasyon max-prob'u amplify ediyor mu?
    try:
        cal_result = _raw_apply_calibration(probs_before)
        if cal_result is None:
            return False
        raw_max = float(probs_before.max())
        cal_max = float(cal_result.max())
        if cal_max > raw_max + _CAL_AMPLIFICATION_THRESHOLD:
            return False  # kalibrasyon overconfidence KATIYOR → SKIP
    except Exception:
        return False

    return True


def _raw_apply_calibration(probs: np.ndarray) -> "np.ndarray | None":
    """Dahili — trust check ve diğer yerlerde kullanmak için pure calibration."""
    if not _SKLEARN_VAR or not os.path.exists(CALIBRATOR_PATH):
        return None
    try:
        with open(CALIBRATOR_PATH, "rb") as f:
            calibrators = pickle.load(f)
    except Exception:
        return None

    probs_arr = np.array(probs, dtype=np.float64)
    is_1d = len(probs_arr.shape) == 1
    if is_1d:
        probs_arr = probs_arr.reshape(1, -1)

    n_classes = probs_arr.shape[1]
    new_probs = np.zeros_like(probs_arr, dtype=np.float64)

    for c in range(n_classes):
        cal = calibrators.get(c)
        if not cal:
            return None
        model = cal["model"]
        method = cal["method"]
        probe_c = probs_arr[:, c]
        if method == "isotonic":
            new_probs[:, c] = model.predict(probe_c)
        elif method == "platt":
            new_probs[:, c] = model.predict_proba(probe_c.reshape(-1, 1))[:, 1]
        else:
            return None

    # Isotonic dominant-class amplification guard:
    # Eğer isotonic herhangi bir sınıfı %90 üstüne itiyorsa etkiyi %50 karıştır
    if new_probs.max() > 0.90:
        # blend: 50% isotonic + 50% raw
        new_probs = 0.5 * new_probs + 0.5 * probs_arr

    row_sums = new_probs.sum(axis=1)
    row_sums[row_sums == 0] = 1e-9
    new_probs = new_probs / row_sums[:, np.newaxis]

    return new_probs[0] if is_1d else new_probs


def apply_calibration(probs):
    """
    Public API — backward compat. CalibrationError raise eder.
    tahmin_yap() artık _is_calibration_trustworthy() ile kontrol yapıyor;
    bu fonksiyon doğrudan kullanılıyorsa da tutarlı davranır.
    """
    if not _SKLEARN_VAR:
        raise CalibrationError("sklearn yok — apply_calibration kullanılamaz")
    if not os.path.exists(CALIBRATOR_PATH):
        raise CalibrationError(
            "calibrator.pkl bulunamadi — gbm egit sonrasi ensure_calibrator_if_missing calistirin"
        )
    result = _raw_apply_calibration(np.array(probs, dtype=np.float64))
    if result is None:
        raise CalibrationError("Kalibrasyon uygulanamadı — calibrator.pkl bozuk")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. ANA PIPELINE  (raw → overconf → calibrate → safe_cap → normalize)
# ─────────────────────────────────────────────────────────────────────────────

def apply_probability_pipeline(raw_probs: np.ndarray) -> dict:
    """
    Tam probability pipeline. Döndürür:
    {
      "probs":                 np.ndarray(3,),
      "calibration_used":     bool,
      "overconfidence_applied": bool,
      "safe_cap_applied":     bool,
      "before":               list,
      "after":                list,
      "max_before":           float,
      "max_after":            float,
    }

    Sıra: raw → overconf_fix → calibrate (güvenilirse) → safe_cap(0.80) → normalize
    """
    probs = np.array(raw_probs, dtype=np.float64).copy()
    raw_max = float(probs.max())
    before = probs.tolist()
    max_before = raw_max

    # Adım 1: Tiered overconfidence fix (scale, henüz normalize etme)
    probs_scaled = _tiered_overconfidence_fix(probs.copy())
    oc_applied = bool(probs_scaled.max() < probs.max() - 1e-9)  # scale azaltma oldu mu?
    # Normalize
    s = probs_scaled.sum()
    probs = probs_scaled / s if s > 0 else probs_scaled

    # Adım 2: Calibration (sadece güvenilirse)
    cal_used = False
    if _is_calibration_trustworthy(probs):
        cal_result = _raw_apply_calibration(probs)
        if cal_result is not None:
            probs = np.array(cal_result, dtype=np.float64)
            cal_used = True

    # Adım 3: Safe mode cap — dominant class tam 0.80'e sabitlenir,
    # kalan sınıflar orantılı olarak 0.20 bütçesine küçültülür, sonra normalize.
    # [0.85, 0.10, 0.05] → [0.80, 0.1333, 0.0667] → normalize → [0.80, 0.133, 0.067]
    safe_applied = False
    if probs.max() > 0.80:
        safe_applied = True
        idx = int(probs.argmax())
        rest_sum = float(probs.sum() - probs[idx])
        probs_capped = probs.copy()
        probs_capped[idx] = 0.80
        if rest_sum > 1e-9:
            scale = 0.20 / rest_sum
            for i in range(len(probs_capped)):
                if i != idx:
                    probs_capped[i] *= scale
        probs = probs_capped

    # Normalize (toplam tam 1.0'a tamamla)
    s = probs.sum()
    if s > 0:
        probs = probs / s

    max_after = float(probs.max())

    return {
        "probs":                  probs,
        "calibration_used":       cal_used,
        "overconfidence_applied": oc_applied,
        "safe_cap_applied":       safe_applied,
        "before":                 before,
        "after":                  probs.tolist(),
        "max_before":             max_before,
        "max_after":              max_after,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. GENİŞLETİLMİŞ LOG
# ─────────────────────────────────────────────────────────────────────────────

def log_calibration_distribution(probs_before, probs_after,
                                  overconfidence_applied: bool = False,
                                  calibration_used: bool = False,
                                  safe_cap_applied: bool = False):
    """
    Genişletilmiş log — her tahmin için bir satır JSONL.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    b = np.asarray(probs_before, dtype=np.float64).ravel()
    a = np.asarray(probs_after, dtype=np.float64).ravel()
    rec = {
        "ts":                   datetime.now(timezone.utc).isoformat(),
        "before_mean":          float(np.mean(b)),
        "before_max":           float(np.max(b)),
        "before_min":           float(np.min(b)),
        "after_mean":           float(np.mean(a)),
        "after_max":            float(np.max(a)),
        "after_min":            float(np.min(a)),
        "before":               b.tolist(),
        "after":                a.tolist(),
        "overconfidence_applied": overconfidence_applied,
        "calibration_used":     calibration_used,
        "safe_cap_applied":     safe_cap_applied,
    }
    with open(CAL_DIST_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# 6. BACKWARD COMPAT
# ─────────────────────────────────────────────────────────────────────────────

def calibrate_probability(prob):
    """
    Tekil olasılık (gol/O-U modelleri). Kimlik dönüşümü + overconf fix.
    """
    try:
        p = float(prob)
        return apply_overconfidence_fix(p)
    except (TypeError, ValueError):
        return prob
