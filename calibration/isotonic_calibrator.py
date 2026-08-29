import os
import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
import logging

logger = logging.getLogger("isotonic_calib")

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CALIBRATOR_PATH = os.path.join(MODEL_DIR, "isotonic_calibrators.pkl")

class IsotonicCalibrator:
    """
    Football Isotonic Calibrator.
    Maps raw predicted probabilities to empirical realities using strictly monotonic mapping.
    Fixes the 'overconfidence' and 'probability explosion' problem.
    """
    def __init__(self):
        self.calibrators = {
            "home": IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99),
            "draw": IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99),
            "away": IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        }
        self.is_fitted = False
    
    def fit(self, y_pred: dict, y_true: dict):
        """
        y_pred: dict of lists -> {"home": [0.4, 0.6...], "draw": [...], "away": [...]}
        y_true: dict of lists -> {"home": [1, 0, ...], "draw": [...], "away": [...]}
        """
        try:
            for outcome in ["home", "draw", "away"]:
                if len(y_pred[outcome]) > 0:
                    self.calibrators[outcome].fit(y_pred[outcome], y_true[outcome])
            self.is_fitted = True
            self.save_model()
            logger.info("Successfully fitted and saved Isotonic Calibrators.")
        except Exception as e:
            logger.error(f"Failed to fit Isotonic Calibrators: {e}")
    
    def predict_proba(self, home_raw: float, draw_raw: float, away_raw: float) -> tuple:
        """
        Takes raw uncalibrated probabilities and returns (calibrated_home, calibrated_draw, calibrated_away).
        """
        if not self.is_fitted:
            self.load_model()
            
        if not self.is_fitted:
            # Fallback if no model exists (e.g. cold start)
            _t = home_raw + draw_raw + away_raw
            return home_raw/_t, draw_raw/_t, away_raw/_t
            
        try:
            h_cal = self.calibrators["home"].predict([home_raw])[0]
            d_cal = self.calibrators["draw"].predict([draw_raw])[0]
            a_cal = self.calibrators["away"].predict([away_raw])[0]
            
            # Bound outputs
            h_cal = max(0.01, min(0.99, h_cal))
            d_cal = max(0.01, min(0.99, d_cal))
            a_cal = max(0.01, min(0.99, a_cal))
            
            # Normalize to sum to 1.0
            total = h_cal + d_cal + a_cal
            return (h_cal / total, d_cal / total, a_cal / total)
        except Exception as e:
            logger.error(f"Error predicting calibrated probs: {e}")
            _t = home_raw + draw_raw + away_raw
            return home_raw/_t, draw_raw/_t, away_raw/_t

    def save_model(self):
        os.makedirs(MODEL_DIR, exist_ok=True)
        joblib.dump(self.calibrators, CALIBRATOR_PATH)
        
    def load_model(self):
        if os.path.exists(CALIBRATOR_PATH):
            try:
                self.calibrators = joblib.load(CALIBRATOR_PATH)
                self.is_fitted = True
            except Exception as e:
                logger.error(f"Error loading calibrator: {e}")
                self.is_fitted = False
        else:
            self.is_fitted = False

# Singleton instance
calibrator_engine = IsotonicCalibrator()

def apply_probability_pipeline(*args, **kwargs) -> dict:
    """
    Public API to calibrate probabilities. Ensures probabilities map accurately to historical results.
    Accepts:
      - (home_prob, draw_prob, away_prob)
      - ([home_prob, draw_prob, away_prob])
      - raw_probs=np.ndarray
    """
    if "raw_probs" in kwargs:
        p = kwargs["raw_probs"]
        h, d, a = p[0], p[1], p[2]
    elif len(args) == 1:
        p = args[0]
        if hasattr(p, '__len__') and len(p) == 3:
            h, d, a = p[0], p[1], p[2]
        else:
            h, d, a = p, 0.28, 1.0 - p - 0.28
    elif len(args) == 3:
        h, d, a = args[0], args[1], args[2]
    else:
        h, d, a = 0.33, 0.34, 0.33

    cal_h, cal_d, cal_a = calibrator_engine.predict_proba(float(h), float(d), float(a))
    probs_arr = np.array([cal_h, cal_d, cal_a], dtype=np.float64)
    return {
        "probs": probs_arr,
        "calibrated_tuple": (cal_h, cal_d, cal_a),
        "calibration_used": calibrator_engine.is_fitted
    }

