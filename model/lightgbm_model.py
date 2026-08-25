# models/lightgbm_model.py
"""
LightGBM Meta-Learner — Düzeltilmiş Versiyon
─────────────────────────────────────────────
DEĞİŞİKLİKLER:
  • pandas, sklearn importları opsiyonel hale getirildi
    (kurulu değilse sistem çalışmaya devam eder)
  • predict_match() artık model olmadan da güvenli çalışır
  • train_model() sadece veri varsa çağrılır
"""

try:
    import lightgbm as lgb
    _LGB_VAR = True
except ImportError:
    _LGB_VAR = False

import sys
import os
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calibration.calibration import calibrate_probability
except:
    def calibrate_probability(prob): return prob

try:
    import pandas as pd
    _PANDAS_VAR = True
except ImportError:
    _PANDAS_VAR = False

try:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import log_loss
    _SKLEARN_VAR = True
except ImportError:
    _SKLEARN_VAR = False


def train_model(df):
    """
    LightGBM modeli eğitir.
    Gerekli kütüphaneler yoksa None döner.
    """
    if not _LGB_VAR or not _PANDAS_VAR or not _SKLEARN_VAR:
        print("  ⚠️  LightGBM/pandas/sklearn kurulu değil — model eğitilemiyor.")
        print("       Kurmak için: pip install lightgbm pandas scikit-learn")
        return None

    X = df.drop(columns=["result"])
    y = df["result"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = lgb.LGBMClassifier(
        n_estimators=800,
        learning_rate=0.03,
        num_leaves=50,
        verbose=-1
    )
    model.fit(X_train, y_train)

    preds = model.predict_proba(X_test)
    print(f"  ✅ LightGBM eğitildi — LogLoss: {log_loss(y_test, preds):.4f}")
    return model


def predict_match(model, features):
    """
    Eğitilmiş model ile tahmin üretir.
    model=None ise varsayılan değerler döner (sistem çökmez).
    """
    if model is None or not _PANDAS_VAR:
        return {"home": 0.40, "draw": 0.28, "away": 0.32}

    X = pd.DataFrame([features])
    probs = model.predict_proba(X)[0]
    return {
        "home": calibrate_probability(float(probs[0])),
        "draw": calibrate_probability(float(probs[1])),
        "away": calibrate_probability(float(probs[2]))
    }