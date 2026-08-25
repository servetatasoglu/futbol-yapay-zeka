from collections import defaultdict
import math

class PortfolioRiskEngine:
    """
    Hedfe Fund düzeyinde makro risk kontrolü. 
    Tekil bir bahsin kaybetme riskinden ziyade; aynı anda açık olan tüm pozisyonların
    (exposure), lig bazlı korelasyonların ve ardışık çöküşlerin portföyü patlatmasını engeller.
    """
    
    def __init__(self, max_portfolio_exposure: float = 0.15, max_league_exposure: float = 0.05):
        """
        max_portfolio_exposure: Kasanın maksimum % kaçı aynı anda riske edilebilir.
        max_league_exposure: Tek bir ligde maksimum % kaç kasa riske edilebilir.
        """
        self.max_exposure = max_portfolio_exposure
        self.max_league_exposure = max_league_exposure
        
        self.active_exposure = 0.0
        self.league_exposure = defaultdict(float)
        
    def check_exposure_limit(self, bet_league: str, requested_stake_pct: float) -> dict:
        """
        Eğer yeni bahis limitleri aşıyorsa Kelly kesici (multiplier) devreye girer.
        """
        multiplier = 1.0
        kill_switch = False
        
        # Portfolio Limit Check
        if self.active_exposure + requested_stake_pct > self.max_exposure:
            available = max(0, self.max_exposure - self.active_exposure)
            if available <= 0.001:
                kill_switch = True
                multiplier = 0.0
            else:
                multiplier = available / requested_stake_pct
                
        # League Limit Check
        current_lg_exp = self.league_exposure[bet_league]
        if current_lg_exp + requested_stake_pct > self.max_league_exposure:
            available_lg = max(0, self.max_league_exposure - current_lg_exp)
            if available_lg <= 0.001:
                kill_switch = True
                multiplier = 0.0
            else:
                lg_multiplier = available_lg / requested_stake_pct
                multiplier = min(multiplier, lg_multiplier)
                
        final_stake = requested_stake_pct * multiplier
        
        return {
            "approved_stake": round(final_stake, 4),
            "kelly_multiplier": round(multiplier, 2),
            "kill_switch_active": kill_switch
        }
        
    def register_bet(self, bet_league: str, executed_stake_pct: float):
        """ Bahis alındığında Exposure artar """
        self.active_exposure += executed_stake_pct
        self.league_exposure[bet_league] += executed_stake_pct
        
    def resolve_bet(self, bet_league: str, executed_stake_pct: float):
        """ Maç bittiğinde Exposure serbest kalır """
        self.active_exposure = max(0.0, self.active_exposure - executed_stake_pct)
        self.league_exposure[bet_league] = max(0.0, self.league_exposure[bet_league] - executed_stake_pct)

    @staticmethod
    def calculate_drawdown_pressure(peak_bankroll: float, current_bankroll: float) -> float:
        """
        Derin bir Drawdown içindeyken (örn. -%15) risk iştahını kapatmak için 
        Basınç İndeksi hesaplar. 1.0 = Normal, 0.1 = Panik/Limit.
        """
        if peak_bankroll <= 0: return 1.0
        
        dd = (peak_bankroll - current_bankroll) / peak_bankroll
        
        # Eğer Drawdown %10'u geçerse Kelly'i katlanarak kıs
        if dd <= 0.05:
            return 1.0
        elif dd <= 0.15:
            return 0.5  # Half-Kelly mode
        elif dd <= 0.25:
            return 0.25 # Quarter-Kelly
        else:
            return 0.05 # Stop-Loss Extreme
