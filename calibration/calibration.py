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
# 1. TRAIN & EVALUATE
# ─────────────────────────────────────────────────────────────────────────────

def calculate_calibration_metrics(y_true: np.ndarray, probs: np.ndarray, n_bins: int = 10) -> dict:
    """
    Kapsamlı kalibrasyon metrikleri:
    - Brier score
    - Log loss
    - ECE (Expected Calibration Error)
    - MCE (Maximum Calibration Error)
    - Sınıf bazında güvenilirlik eğrisi (reliability bins)
    """
    arr1 = np.asarray(y_true)
    arr2 = np.asarray(probs)
    if len(arr1.shape) == 2 and arr1.shape[1] > 1 and len(arr2.shape) == 1:
        probs = np.asarray(arr1, dtype=np.float64)
        y_true = np.asarray(arr2, dtype=int)
    else:
        y_true = np.asarray(arr1, dtype=int)
        probs = np.asarray(arr2, dtype=np.float64)

    n_samples, n_classes = probs.shape

    # One-hot encoded true vector
    y_one_hot = np.zeros_like(probs)
    for i, c in enumerate(y_true):
        if 0 <= c < n_classes:
            y_one_hot[i, c] = 1.0

    # Multi-class Brier Score: mean squared error over classes
    brier = float(np.mean(np.sum((probs - y_one_hot) ** 2, axis=1)))

    # Log Loss
    eps = 1e-12
    p_clipped = np.clip(probs, eps, 1.0 - eps)
    # Re-normalize rows after clipping
    p_clipped = p_clipped / p_clipped.sum(axis=1, keepdims=True)
    logloss = float(-np.mean(np.sum(y_one_hot * np.log(p_clipped), axis=1)))

    # Multiclass ECE & MCE
    confidences = np.max(probs, axis=1)
    predictions = np.argmax(probs, axis=1)
    accuracies = (predictions == y_true).astype(float)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    mce = 0.0
    reliability_bins = []

    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]
        in_bin = (confidences > bin_lower) & (confidences <= bin_upper) if i > 0 else (confidences >= bin_lower) & (confidences <= bin_upper)
        prop_in_bin = float(np.mean(in_bin))

        if prop_in_bin > 0:
            accuracy_in_bin = float(np.mean(accuracies[in_bin]))
            avg_confidence_in_bin = float(np.mean(confidences[in_bin]))
            bin_error = abs(avg_confidence_in_bin - accuracy_in_bin)
            ece += bin_error * prop_in_bin
            mce = max(mce, bin_error)
            reliability_bins.append({
                "bin_range": (round(bin_lower, 2), round(bin_upper, 2)),
                "count": int(np.sum(in_bin)),
                "avg_conf": round(avg_confidence_in_bin, 4),
                "accuracy": round(accuracy_in_bin, 4),
                "error": round(bin_error, 4)
            })

    return {
        "brier_score": round(brier, 4),
        "log_loss": round(logloss, 4),
        "ece": round(float(ece), 4),
        "mce": round(float(mce), 4),
        "n_samples": n_samples,
        "reliability_bins": reliability_bins
    }


evaluate_calibration_metrics = calculate_calibration_metrics


class CalibratorDict(dict):
    """Calibrator dictionary that also provides a scikit-learn compatible predict_proba interface."""

    def predict_proba(self, probs: np.ndarray) -> np.ndarray:
        probs_arr = np.array(probs, dtype=np.float64)
        is_1d = (len(probs_arr.shape) == 1)
        if is_1d:
            probs_arr = probs_arr.reshape(1, -1)

        n_classes = probs_arr.shape[1]
        if self.get("_global_method") == "temperature":
            T = float(self.get("_temperature", 1.0))
            eps = 1e-7
            logits = np.log(np.clip(probs_arr, eps, 1.0 - eps))
            scaled = logits / max(T, 0.05)
            exp_s = np.exp(scaled - np.max(scaled, axis=1, keepdims=True))
            new_probs = exp_s / np.sum(exp_s, axis=1, keepdims=True)
            return new_probs[0] if is_1d else new_probs

        new_probs = np.zeros_like(probs_arr, dtype=np.float64)
        for c in range(n_classes):
            cal = self.get(c)
            if not cal:
                continue
            model = cal["model"]
            method = cal["method"]
            probe_c = probs_arr[:, c]
            if method == "isotonic":
                new_probs[:, c] = model.predict(probe_c)
            elif method == "platt":
                new_probs[:, c] = model.predict_proba(probe_c.reshape(-1, 1))[:, 1]
            elif method == "beta":
                eps = 1e-6
                pr = np.clip(probe_c, eps, 1.0 - eps)
                feat = np.column_stack([np.log(pr), -np.log(1.0 - pr)])
                new_probs[:, c] = model.predict_proba(feat)[:, 1]

        row_sums = np.sum(new_probs, axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        new_probs = new_probs / row_sums
        return new_probs[0] if is_1d else new_probs


def train_calibrator_oof(X_oof_probs: np.ndarray, y_true: np.ndarray, method: str = "isotonic") -> CalibratorDict:
    """
    YALNIZCA Out-Of-Fold (OOF) cross-validation tahminleri ile kalibratör eğitir.
    In-sample eğitim sızıntısını kesinlikle engeller.
    """
    return train_calibrator(X_oof_probs, y_true, method=method, is_oof=True)


def train_calibrator(X_probs, y_true, method="isotonic", is_oof=False):
    """
    X_probs: shape (n_samples, n_classes) — uncalibrated ensemble probs
    y_true : shape (n_samples,)           — integer class labels (0,1,2)

    One-vs-Rest isotonic/platt/beta veya multi-class temperature scaling.
    Kaydedilir: data/calibrator.pkl
    """
    if not _SKLEARN_VAR:
        raise CalibrationError("sklearn yok — isotonic kalibrasyon eğitilemez")

    X_probs = np.asarray(X_probs, dtype=np.float64)
    y_true = np.asarray(y_true, dtype=int)
    n_classes = X_probs.shape[1]

    calibrators = CalibratorDict()
    calibrators["_metadata"] = {
        "method": method,
        "is_oof": is_oof,
        "n_samples": len(y_true),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if method == "temperature":
        # Global temperature optimization (NLL minimization)
        from scipy.optimize import minimize
        eps = 1e-7
        logits = np.log(np.clip(X_probs, eps, 1.0 - eps))

        def nll(T):
            T = max(T[0], 0.05)
            scaled = logits / T
            exp_s = np.exp(scaled - np.max(scaled, axis=1, keepdims=True))
            probs_s = exp_s / np.sum(exp_s, axis=1, keepdims=True)
            y_one_hot = np.zeros_like(probs_s)
            for i, c in enumerate(y_true):
                y_one_hot[i, c] = 1.0
            return -np.mean(np.sum(y_one_hot * np.log(np.clip(probs_s, eps, 1.0)), axis=1))

        res = minimize(nll, [1.0], bounds=[(0.1, 5.0)], method="L-BFGS-B")
        T_opt = float(res.x[0]) if res.success else 1.0
        calibrators["_temperature"] = T_opt
        calibrators["_global_method"] = "temperature"

    elif method == "beta":
        # Beta calibration: logistic on log(p) and log(1-p)
        eps = 1e-6
        for c in range(n_classes):
            y_c = (y_true == c).astype(int)
            probe_c = np.clip(X_probs[:, c], eps, 1.0 - eps)
            feat = np.column_stack([np.log(probe_c), -np.log(1.0 - probe_c)])
            cal = LogisticRegression(C=1.0)
            cal.fit(feat, y_c)
            calibrators[c] = {"model": cal, "method": "beta"}

    else:
        # One-vs-Rest isotonic or platt
        for c in range(n_classes):
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

    # Global method check (e.g. temperature scaling)
    if calibrators.get("_global_method") == "temperature":
        T = float(calibrators.get("_temperature", 1.0))
        eps = 1e-7
        logits = np.log(np.clip(probs_arr, eps, 1.0 - eps))
        scaled = logits / max(T, 0.05)
        exp_s = np.exp(scaled - np.max(scaled, axis=1, keepdims=True))
        new_probs = exp_s / np.sum(exp_s, axis=1, keepdims=True)
        return new_probs[0] if is_1d else new_probs

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
        elif method == "beta":
            eps = 1e-6
            pr = np.clip(probe_c, eps, 1.0 - eps)
            feat = np.column_stack([np.log(pr), -np.log(1.0 - pr)])
            new_probs[:, c] = model.predict_proba(feat)[:, 1]
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
