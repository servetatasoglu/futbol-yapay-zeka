# backtesting/walk_forward.py
"""
Walk-Forward Validation & Performance Gate Controllers
════════════════════════════════════════════════════════════════
Entegrasyon: main.py, tracking/validation.py, tracking/clv_tracker.py
"""

import os
import json
import logging
from tracking.validation import calistir, sonuclari_yukle, filtre_agirliklarini_yukle
from tracking.clv_tracker import clv_raporu

logger = logging.getLogger("walk_forward")

def sharpe_gate_kontrol() -> dict:
    """
    Sharpe Ratio Kontrolü.
    Geçmiş performans Sharpe oranını değerlendirir.
    Returns: {"gecti": bool, "sebep": str, "sharpe": float}
    """
    try:
        from risk.bankroll import bankroll_raporu, get_current_bankroll
        clv_log = os.path.join(os.path.dirname(__file__), "..", "data", "clv_bet_log.json")
        rapor = bankroll_raporu(clv_log, baslangic_banka=1000.0)
        sharpe = rapor.get("sharpe_ratio", 0.0) if isinstance(rapor, dict) else 0.0
        
        if sharpe < -1.5:
            return {
                "gecti": False,
                "sharpe": sharpe,
                "sebep": f"Sharpe katastrofik negatif ({sharpe:.2f} < -1.5) - Risk kapısı aktif"
            }
        return {
            "gecti": True,
            "sharpe": sharpe,
            "sebep": f"Sharpe kabul edilebilir seviyede ({sharpe:.2f})"
        }
    except Exception as e:
        logger.warning(f"Sharpe gate hesaplama uyarısı: {e}")
        return {"gecti": True, "sharpe": 0.0, "sebep": f"Veri yetersiz/Varsayılan Onay ({e})"}


def clv_gate_kontrol() -> dict:
    """
    CLV (Closing Line Value) Gate Kontrolü.
    Piyasa kapanış oranlarına karşı performansı değerlendirir.
    Returns: {"gecti": bool, "sebep": str, "ort_clv": float}
    """
    try:
        rapor = clv_raporu()
        ort_clv = rapor.get("ort_clv")
        disable = rapor.get("execution_disable", False)
        
        if disable:
            return {
                "gecti": False,
                "ort_clv": ort_clv or 0.0,
                "sebep": f"Ortalama CLV yetersiz (%{ (ort_clv or 0)*100:.2f}) - Otomatik Devre Dışı"
            }
        
        clv_str = f"%{(ort_clv*100):.2f}" if ort_clv is not None else "Veri Henüz Yok"
        return {
            "gecti": True,
            "ort_clv": ort_clv,
            "sebep": f"CLV Seviyesi Uygun ({clv_str})"
        }
    except Exception as e:
        logger.warning(f"CLV gate hesaplama uyarısı: {e}")
        return {"gecti": True, "ort_clv": None, "sebep": f"Varsayılan Onay ({e})"}
