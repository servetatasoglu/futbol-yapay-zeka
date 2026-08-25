import numpy as np

class CLVStreamEngine:
    """
    Real-Time CLV Streaming & Decay Tracking Simulator.
    Calculates the erosion or appreciation of edge value throughout the time series.
    """
    
    @staticmethod
    def calculate_clv_decay(entry_odds: float, tick_path: np.ndarray) -> dict:
        """
        Giriş anından (T0) Kapanış Düdüğüne (T_End) kadar geçen sürede CLV'nin 
        nasıl bir decay/appreciation sergilediğini bulur.
        """
        if entry_odds <= 1.0 or tick_path is None or len(tick_path) == 0:
            return {"rolling_clv_curve": [], "decay_rate": 0.0, "max_clv_achieved": 0.0}
            
        rolling_clv = []
        for current_market_odds in tick_path:
            clv_val = (entry_odds / current_market_odds) - 1.0
            rolling_clv.append(round(clv_val * 100, 3)) # Yüzdelik CLV
            
        peak_clv = max(rolling_clv)
        final_clv = rolling_clv[-1]
        
        # Erozyon oranı: Eğer t anında %5 kar yaptıysa ama kapanışa %2 girdiyse decay hesapla.
        if peak_clv > 0 and final_clv < peak_clv:
            decay_rate = (peak_clv - final_clv) / peak_clv
        else:
            decay_rate = 0.0
            
        return {
            "rolling_clv_curve": rolling_clv,      # Equity curve çizimi gibi CLV sörfü için
            "decay_rate_pct": round(decay_rate * 100, 2),
            "max_clv_achieved": peak_clv,
            "final_clv": final_clv
        }

    @staticmethod
    def expected_vs_real_gap(model_p: float, entry_odds: float, closing_odds: float) -> dict:
        """
        Sistemin T0'da beklediği Edge ile piyasanın kapattığı Edge arasındaki fark.
        """
        expected_clv = (model_p * entry_odds) - 1.0
        real_clv = (entry_odds / closing_odds) - 1.0
        
        gap = expected_clv - real_clv
        
        return {
            "expected_clv_pct": round(expected_clv * 100, 2),
            "real_clv_pct": round(real_clv * 100, 2),
            "clv_gap": round(gap * 100, 2)
        }
