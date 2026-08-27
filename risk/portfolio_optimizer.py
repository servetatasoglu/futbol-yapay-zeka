# risk/portfolio_optimizer.py
"""
Portfolio Optimizer — v3.0
════════════════════════════════════════════════════════════
Selects the optimal subset of candidate bets to maximize
portfolio-level EV while respecting:
  - Max 1 bet per league (correlation control)
  - Max 3 total bets per day
  - Max 2% total daily bankroll exposure
  - Correlated outcomes get reduced sizing
  - No same-day bets on teams playing each other

This replaces the naive "take all bets that pass edge filter"
approach which ignores inter-bet correlation and compounds risk.
"""

import logging
from itertools import combinations

logger = logging.getLogger("portfolio_optimizer")

# ── Portfolio constraints ─────────────────────────────────────────
MAX_BETS_GUNLUK        = 3      # Max bets per day
MAX_EXPOSURE_GUNLUK    = 0.02   # Max 2% total daily bankroll exposure
MAX_BETS_AYNI_LIG      = 1      # Max 1 bet from same league
MAX_BETS_AYNI_TAKIM    = 0      # 0 = never bet on same team twice same day
MIN_BET_CONFIDENCE     = 0.30   # Min composite confidence to enter portfolio

# ── Correlation penalties ─────────────────────────────────────────
# Same-league bets are correlated (weather, form, fixture bias)
SAME_LIG_KORELASYON    = 0.35   # 35% correlation assumed for same-league bets
# Cross-league correlation baseline (macro market moves together)
CROSS_LIG_KORELASYON   = 0.10


def _ev_hesapla(olasilik: float, oran: float) -> float:
    """Expected Value per unit staked."""
    if oran <= 1.0 or olasilik <= 0:
        return 0.0
    return olasilik * (oran - 1) - (1 - olasilik)


def _korelasyon_carpan(bets: list) -> float:
    """
    Estimate portfolio correlation penalty.
    Same-league pairs are more correlated.
    Returns a multiplier in [0.5, 1.0].
    """
    if len(bets) < 2:
        return 1.0

    total_corr = 0.0
    pairs = 0
    for b1, b2 in combinations(bets, 2):
        lig1 = b1.get("lig_kodu", b1.get("lig", "?"))
        lig2 = b2.get("lig_kodu", b2.get("lig", "?"))
        corr = SAME_LIG_KORELASYON if lig1 == lig2 else CROSS_LIG_KORELASYON
        total_corr += corr
        pairs += 1

    avg_corr = total_corr / pairs if pairs > 0 else 0
    # High correlation reduces portfolio efficiency
    return round(max(0.5, 1.0 - avg_corr * 0.8), 3)


def _portfolio_ev(bets: list) -> float:
    """
    Portfolio-level expected value (sum of stake_size * EV, penalized by correlation).
    """
    total_ev = sum(
        _ev_hesapla(b.get("olasilik", 0.5), b.get("oran", 2.0)) * b.get("size", b.get("kelly_size", 0.01))
        for b in bets
    )
    corr_pen = _korelasyon_carpan(bets)
    return total_ev * corr_pen


def _is_valid_portfolio(bets: list) -> tuple:
    """
    Check portfolio constraints.
    Returns (valid: bool, reason: str).
    """
    if len(bets) > MAX_BETS_GUNLUK:
        return False, f"exceeds_max_bets({len(bets)} > {MAX_BETS_GUNLUK})"

    # League uniqueness
    ligler = [b.get("lig_kodu", b.get("lig", "?")) for b in bets]
    if len(ligler) != len(set(ligler)):
        return False, "duplicate_league"

    # Team uniqueness (same team cannot appear twice)
    takimlar = []
    for b in bets:
        takimlar.append(b.get("ev_db", b.get("ev", "")))
        takimlar.append(b.get("dep_db", b.get("dep", "")))
    if len(takimlar) != len(set(takimlar)):
        return False, "duplicate_team"

    return True, "ok"


def optimize_portfolio(
    candidate_bets: list,
    bankroll: float = 5000.0,
    mevcut_bahisler: list = None,
) -> dict:
    """
    Select optimal portfolio from candidate bets.

    Args:
        candidate_bets:  Bets from value_betleri_bul (already edge-validated)
        bankroll:        Current bankroll
        mevcut_bahisler: Already placed bets today (to check exposure/limits)

    Returns:
        {
            "secilen_bahisler":  list,   # Optimal bet subset
            "red_edilenler":     list,   # Rejected bets with reasons
            "portfoy_ev":        float,  # Total portfolio EV
            "korelasyon_carpan": float,
            "toplam_exposure":   float,  # Total bankroll exposure
            "kisitlar":          dict,   # Which constraints are active
        }
    """
    mevcut = mevcut_bahisler or []
    mevcut_ligler = {b.get("lig_kodu", b.get("lig", "?")) for b in mevcut}
    mevcut_takimlar = set()
    for b in mevcut:
        mevcut_takimlar.add(b.get("ev_db", b.get("ev", "")))
        mevcut_takimlar.add(b.get("dep_db", b.get("dep", "")))

    # Daily exposure already used
    mevcut_exposure = sum(b.get("size", b.get("kelly_size", 0)) for b in mevcut)
    kalan_exposure  = max(0, MAX_EXPOSURE_GUNLUK - mevcut_exposure)
    kalan_slot      = max(0, MAX_BETS_GUNLUK - len(mevcut))

    if kalan_slot == 0:
        logger.info("Portfolio: Daily bet limit reached.")
        return {
            "secilen_bahisler": [],
            "red_edilenler": candidate_bets,
            "portfoy_ev": 0,
            "korelasyon_carpan": 1.0,
            "toplam_exposure": mevcut_exposure,
            "kisitlar": {"sebep": "gunluk_limit_doldu"},
        }

    # Pre-filter: remove bets conflicting with existing positions
    pre_filtered = []
    on_red = []
    for bet in candidate_bets:
        lig  = bet.get("lig_kodu", bet.get("lig", "?"))
        ev   = bet.get("ev_db",  bet.get("ev",  ""))
        dep  = bet.get("dep_db", bet.get("dep", ""))
        conf = bet.get("validation", {}).get("confidence", 1.0)

        reason = None
        if lig in mevcut_ligler:
            reason = f"lig_zaten_var({lig})"
        elif ev in mevcut_takimlar or dep in mevcut_takimlar:
            reason = "takim_zaten_var"
        elif conf < MIN_BET_CONFIDENCE:
            reason = f"dusuk_guven({conf:.2f})"

        if reason:
            bet["red_sebebi"] = reason
            on_red.append(bet)
        else:
            pre_filtered.append(bet)

    if not pre_filtered:
        return {
            "secilen_bahisler": [],
            "red_edilenler": on_red + candidate_bets,
            "portfoy_ev": 0,
            "korelasyon_carpan": 1.0,
            "toplam_exposure": mevcut_exposure,
            "kisitlar": {"sebep": "on_filtre_bosaltti"},
        }

    # Sort by: validation confidence × adjusted_edge (descending)
    pre_filtered.sort(
        key=lambda b: (
            b.get("validation", {}).get("confidence", 0.5) *
            b.get("validation", {}).get("adjusted_edge", b.get("efektif_edge", 0))
        ),
        reverse=True
    )

    # Enumerate valid portfolios up to kalan_slot bets
    best_portfolio = []
    best_ev        = -999.0
    red_edilenler  = list(on_red)

    max_n = min(kalan_slot, len(pre_filtered))

    for n in range(1, max_n + 1):
        for combo in combinations(pre_filtered, n):
            valid, _ = _is_valid_portfolio(list(combo))
            if not valid:
                continue

            # Exposure check
            combo_exposure = sum(
                b.get("size", b.get("kelly_size", 0.005)) for b in combo
            )
            if mevcut_exposure + combo_exposure > MAX_EXPOSURE_GUNLUK * 1.05:
                continue  # 5% tolerance

            port_ev = _portfolio_ev(list(combo))
            if port_ev > best_ev:
                best_ev        = port_ev
                best_portfolio = list(combo)

    # Mark rejected bets
    selected_ids = {id(b) for b in best_portfolio}
    for bet in pre_filtered:
        if id(bet) not in selected_ids:
            bet["red_sebebi"] = "portfoy_optimizasyonu"
            red_edilenler.append(bet)

    total_exposure = mevcut_exposure + sum(
        b.get("size", b.get("kelly_size", 0.005)) for b in best_portfolio
    )
    corr_pen = _korelasyon_carpan(best_portfolio)

    logger.info(
        f"Portfolio: {len(best_portfolio)} bets selected from "
        f"{len(candidate_bets)} candidates | "
        f"EV={best_ev:.4f} | corr={corr_pen:.2f} | "
        f"exposure={total_exposure:.3f}"
    )

    return {
        "secilen_bahisler":  best_portfolio,
        "red_edilenler":     red_edilenler,
        "portfoy_ev":        round(best_ev, 4),
        "korelasyon_carpan": corr_pen,
        "toplam_exposure":   round(total_exposure, 4),
        "kisitlar": {
            "kalan_slot":      kalan_slot,
            "kalan_exposure":  round(kalan_exposure, 4),
            "mevcut_ligler":   list(mevcut_ligler),
        },
    }
