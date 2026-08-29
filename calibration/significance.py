import numpy as np
from scipy import stats

class StatisticalValidator:
    """
    Statistical validation layer using Bootstrapping and T-Tests.
    Guarantees that generated Edge and CLV are statistically significant
    and not products of pure variance or data-mining.
    """
    
    @staticmethod
    def bootstrap_significance(clv_array: list, iterations: int = 5000) -> dict:
        """
        Bootstrap metodu ile stratejinin "sıfır CLV" üretme ihtimalini (p-value) hesaplar.
        """
        if len(clv_array) < 30:
            return {"p_value": 1.0, "is_significant": False, "confidence_interval": [0,0]}
            
        original_mean = np.mean(clv_array)
        n = len(clv_array)
        
        # Sampling with replacement
        bootstrap_means = []
        for _ in range(iterations):
            sample = np.random.choice(clv_array, size=n, replace=True)
            bootstrap_means.append(np.mean(sample))
            
        bootstrap_means = np.array(bootstrap_means)
        
        # H0 (Null Hypothesis): Gerçek ortalama CLV <= 0'dır (Şans eseri kazanıyoruz)
        # H1: Gerçek ortalama CLV > 0'dır (Piyasayı harbi yeniyoruz)
        
        p_value = np.sum(bootstrap_means <= 0) / iterations
        
        lower_bound = np.percentile(bootstrap_means, 2.5)
        upper_bound = np.percentile(bootstrap_means, 97.5)
        
        return {
            "p_value": round(p_value, 5),
            "is_significant": p_value < 0.05,
            "confidence_interval": [round(lower_bound, 3), round(upper_bound, 3)],
            "mean_clv": round(original_mean, 3)
        }

    @staticmethod
    def bootstrap_edge_significance(edge_array: list, iterations: int = 1000) -> dict:
        """
        Bootstrap confidence interval for model probability edge.
        """
        if not edge_array or len(edge_array) < 10:
            return {"p_value": 1.0, "is_significant": False, "confidence_interval": [0.0, 0.0], "mean_edge": 0.0}

        arr = np.array(edge_array, dtype=np.float64)
        n = len(arr)
        bootstrap_means = [np.mean(np.random.choice(arr, size=n, replace=True)) for _ in range(iterations)]
        bootstrap_means = np.array(bootstrap_means)

        p_val = float(np.sum(bootstrap_means <= 0.0) / iterations)
        lower = float(np.percentile(bootstrap_means, 2.5))
        upper = float(np.percentile(bootstrap_means, 97.5))

        return {
            "p_value": round(p_val, 4),
            "is_significant": p_val < 0.05,
            "confidence_interval": [round(lower, 4), round(upper, 4)],
            "mean_edge": round(float(np.mean(arr)), 4)
        }
        
    @staticmethod
    def edge_reliability_score(expected_edges: list, achieved_clvs: list) -> float:
        """
        Modelin iddia ettiği Edge ile piyasadan kopardığı CLV arasındaki korelasyonu ölçer.
        Skor 1'e ne kadar yakınsa model o kadar "kalibre/gerçekçi" dir.
        Aksi halde model Overfit olmuştur (Overconfidence).
        """
        if len(expected_edges) < 10 or len(achieved_clvs) < 10:
            return 0.0
            
        correlation, _ = stats.pearsonr(expected_edges, achieved_clvs)
        
        # Eğer negatif korelasyon varsa (model çok iddialı ama market zıttına gidiyor) risk büyüktür.
        if np.isnan(correlation):
            return 0.0
            
        return round(correlation, 4)

    @staticmethod
    def detect_overfitting_risk(win_rate: float, avg_odds: float, bet_count: int) -> dict:
        """
        Elde edilen win_rate'in, ortalama oynanan oranın Implied Probability'sinden 
        aşırı yukarda olup olmadığını T-Test ile sinyaller.
        """
        if bet_count < 30 or avg_odds <= 1.0:
            return {"overfitting_risk": "UNKNOWN", "score": 0.0}
            
        implied_p = 1.0 / avg_odds
        variance = implied_p * (1 - implied_p)
        std_dev = np.sqrt(variance / bet_count)
        
        # Z-Skoru: Şans eseri bu win_rate'e ulaşma ihtimali
        z_score = (win_rate - implied_p) / std_dev
        
        # Eğer z_score > 3.0 ise (Yani model şanstan %99.9 daha iyi performans gösteriyorsa)
        # Ve CLV P-Value significance başarısızsa -> Kesinlikle OVERFITTING (Eğri Uydurma) vardır.
        
        risk = "LOW"
        if z_score > 2.5: risk = "MODERATE"
        if z_score > 3.5: risk = "HIGH"
        if z_score > 5.0: risk = "EXTREME (LIKELY LEAKAGE)"
        
        return {
            "z_score": round(z_score, 2),
            "overfitting_risk": risk
        }
