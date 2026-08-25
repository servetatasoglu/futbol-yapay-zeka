import numpy as np

class MicrostructureSimulator:
    """
    Hedge Fund Market Microstructure model for sports betting.
    Simulates real-time order matching, liquidity, slippage, and fill probability.
    """
    
    @staticmethod
    def simulate_tick_path(odds_open: float, odds_close: float, periods: int = 100) -> np.ndarray:
        """
        Geometrik Brownian Motion kullanarak Açılış ve Kapanış oranları arasında 
        zaman bazlı rasyonel 'tick' noktaları (anlık oran kaymaları) simüle eder.
        """
        if odds_open <= 1.0 or odds_close <= 1.0:
            return np.full(periods, odds_open)
            
        # Logarithmic return trajectory
        mu = np.log(odds_close / odds_open)
        
        # Volatilite, piyasadaki marjin değişimlerine kıyasla atanır 
        # (Futbol marketlerinde maç sonuca yaklaşırken volatilite bellidir)
        volatility = 0.05 * abs(mu) + 0.02 
        
        dt = 1.0 / periods
        path = np.zeros(periods)
        path[0] = odds_open
        
        for t in range(1, periods):
            # Drift ve Diffusion
            drift = (mu - 0.5 * volatility**2) * dt
            diffusion = volatility * np.sqrt(dt) * np.random.normal()
            path[t] = path[t-1] * np.exp(drift + diffusion)
            
        # Son periyodu tam olarak closing'e hizala ki backtest bozulmasın
        path[-1] = odds_close
        return path

    @staticmethod
    def calculate_execution_quality(target_odds: float, bet_size: float, market_volatility: float) -> dict:
        """
        Emir iletildiği anda (Fill request) emrin beklediği fiyatattan doldurulup 
        doldurulmayacağını (Fill Probability) ve olası kaymayı (Slippage) hesaplar.
        """
        # Standart Likidite Prims'i hesaplaması
        # Yüksek oranlarda (Sürprizler) likidite çok azdır, dolayısıyla slippage yeme ihtimali çok yüksektir.
        base_liquidity = 1.0 / target_odds  
        
        # Bet size ne kadar büyürse Market Impact o kadar artar
        # 10,000$ üzeri işlemlerde Impact hissedilir başlar.
        market_impact = (bet_size / 100000.0) * (1.0 / base_liquidity)
        
        # Gecikme ve Volatilitesi yüksek pazarda kayma (slippage) artar
        expected_slippage = market_volatility * 0.5 + market_impact
        # En kötü ihtimalle oran aşağı kayacak:
        executed_odds = target_odds * (1 - expected_slippage)
        if executed_odds <= 1.01:
            executed_odds = 1.01
            
        # Order Fill Probability (Eğer edge çok barizse ve market hızla çökmüşse, broker limit emrinizi reddedebilir)
        fill_prob = np.exp(-market_impact * 2) - (market_volatility * 0.1)
        fill_prob = max(0.1, min(1.0, fill_prob))
        
        return {
            "fill_probability": round(fill_prob, 4),
            "expected_slippage_bps": round(expected_slippage * 10000, 2), # Basis points
            "executed_odds": round(executed_odds, 3),
            "market_impact_cost": round(target_odds - executed_odds, 3)
        }
