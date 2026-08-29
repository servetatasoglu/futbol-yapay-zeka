"""
test_audit_and_production.py
════════════════════════════════════════════════════════════════════════════
Production-Grade Verification Suite:
  1. Zero Future Data Leakage Verification (Point-in-Time Features)
  2. Synthetic Data Rejection & No Fake Odds Verification
  3. Mathematical Calibration & Overconfidence Shrinkage Verification
  4. Portfolio EV & Correlation Constraint Verification
  5. Statistical Bootstrap Validator Verification
  6. Walk-Forward Backtesting Engine Verification
"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_zero_leakage_point_in_time():
    """
    Test that point-in-time ELO computation strictly depends only on matches
    occurring before the match timestamp (t < match_date), with zero future leakage.
    """
    from features.elo import elo_point_in_time_hesapla

    # Create historical matches where Arsenal wins game 1 and loses game 2
    mock_data = {
        "PL": [
            {
                "id": "M1",
                "homeTeam": {"name": "Arsenal"},
                "awayTeam": {"name": "Chelsea"},
                "score": {"fullTime": {"home": 3, "away": 0}},
                "utcDate": "2026-01-01T15:00:00Z"
            },
            {
                "id": "M2",
                "homeTeam": {"name": "Arsenal"},
                "awayTeam": {"name": "Liverpool"},
                "score": {"fullTime": {"home": 0, "away": 3}},
                "utcDate": "2026-01-10T15:00:00Z"
            }
        ]
    }

    pit = elo_point_in_time_hesapla(mock_data)

    # In M1 (before M1 is played), Arsenal and Chelsea must have starting ELO (1500)
    assert pit["M1"]["ev_elo"] == 1500.0
    assert pit["M1"]["dep_elo"] == 1500.0

    # In M2 (before M2 is played, but after M1), Arsenal's ELO must be increased (> 1500)
    assert pit["M2"]["ev_elo"] > 1500.0
    # Liverpool did not play M1, so their ELO before M2 must be 1500.0
    assert pit["M2"]["dep_elo"] == 1500.0


def test_no_synthetic_odds_fallback():
    """
    Test that canli_oranlar_cek does NOT fabricate placeholder 4.68 odds
    or demo matches when live API feeds return empty.
    """
    from data.odds import canli_oranlar_cek

    # Clean cache and test
    odds = canli_oranlar_cek(zorla_yenile=True)
    # Either returns real scraped/API matches or clean empty list
    for match in odds:
        assert match.get("ber_oran") != 4.68, "Synthetic 4.68 draw odds detected!"
        assert match.get("kaynak") not in ("football-data-hibrit", "demo"), "Fake odds source detected!"


def test_overconfidence_shrinkage():
    """
    Test that _tiered_overconfidence_fix shrinks extreme probabilities
    towards the uniform prior (1/3 for 3 classes) and properly normalizes.
    """
    from calibration.calibration import _tiered_overconfidence_fix

    extreme_probs = np.array([0.90, 0.06, 0.04])
    fixed_probs = _tiered_overconfidence_fix(extreme_probs)

    assert fixed_probs.max() < 0.90, "Extreme probability was not shrunk"
    assert abs(fixed_probs.sum() - 1.0) < 1e-6, "Probabilities do not sum to 1.0"
    assert fixed_probs[0] < 0.80, "Did not apply aggressive shrinkage for > 0.85"


def test_portfolio_ev_calculation():
    """
    Test that portfolio EV calculation correctly reflects sum(stake * EV)
    and applies correlation penalties without exponential squaring.
    """
    from risk.portfolio_optimizer import _portfolio_ev, _ev_hesapla

    bets = [
        {"olasilik": 0.55, "oran": 2.00, "size": 0.01, "lig_kodu": "PL"},
        {"olasilik": 0.55, "oran": 2.00, "size": 0.01, "lig_kodu": "PD"}
    ]
    port_ev = _portfolio_ev(bets)
    assert 0.0015 < port_ev <= 0.0025, f"Portfolio EV {port_ev} out of expected range"


def test_statistical_bootstrap_validator():
    """
    Test bootstrap significance tests on Edge and CLV arrays.
    """
    from calibration.significance import StatisticalValidator

    positive_edges = [0.04, 0.05, 0.03, 0.06, 0.04, 0.05, 0.04, 0.03, 0.05, 0.06, 0.04, 0.05]
    res = StatisticalValidator.bootstrap_edge_significance(positive_edges, iterations=500)
    assert res["is_significant"] is True
    assert res["confidence_interval"][0] > 0.0

    noisy_edges = [-0.02, 0.03, -0.01, 0.02, -0.03, 0.01, -0.01, 0.02, -0.02, 0.01]
    res_noisy = StatisticalValidator.bootstrap_edge_significance(noisy_edges, iterations=500)
    assert res_noisy["is_significant"] is False


def test_walk_forward_backtest_execution():
    """
    Test that the walk-forward backtesting engine runs without error,
    produces valid statistics, and respects bankroll constraints.
    """
    from backtesting.walk_forward import run_walk_forward_backtest

    res = run_walk_forward_backtest(initial_bankroll=1000.0, min_edge=0.01, kelly_fraction=0.20)
    assert "total_bets" in res
    if res["total_bets"] > 0:
        assert 0.0 <= res["win_rate"] <= 1.0
        assert res["final_bankroll"] > 0.0
        assert "mean_brier_score" in res
        assert "mean_log_loss" in res
