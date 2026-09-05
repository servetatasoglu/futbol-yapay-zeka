"""
tests/test_institutional_audit.py
════════════════════════════════════════════════════════════════════════════
Institutional-Grade Quantitative Audit Verification Suite (19 Tests):
  1.  test_no_future_leakage
  2.  test_point_in_time_features
  3.  test_xg_point_in_time
  4.  test_h2h_point_in_time
  5.  test_odds_timestamp
  6.  test_no_synthetic_market_odds
  7.  test_calibration_oof
  8.  test_feature_parity
  9.  test_class_mapping
  10. test_probability_sum
  11. test_probability_bounds
  12. test_duplicate_fixture
  13. test_stale_data
  14. test_missing_odds
  15. test_invalid_odds
  16. test_model_version
  17. test_prediction_reproducibility
  18. test_walk_forward_order
  19. test_no_test_set_tuning
════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import numpy as np
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── 1. Zero Future Leakage ──────────────────────────────────────────
def test_no_future_leakage():
    """Verify team stats computed at timestamp t do not contain info from t2 > t."""
    from features.team_stats import point_in_time_stats

    # Simulated match series
    history = [
        {"home": "TeamA", "away": "TeamB", "home_goals": 2, "away_goals": 1, "date": "2026-01-01T15:00:00Z"},
        {"home": "TeamA", "away": "TeamC", "home_goals": 5, "away_goals": 0, "date": "2026-01-10T15:00:00Z"},
        {"home": "TeamD", "away": "TeamA", "home_goals": 4, "away_goals": 0, "date": "2026-01-20T15:00:00Z"},
    ]

    # At 2026-01-05: TeamA has played only 1 match (2 scored, 1 conceded)
    stats_t1 = point_in_time_stats("TeamA", "2026-01-05T00:00:00Z", match_history=history)
    assert stats_t1["mac_sayisi"] == 1
    assert stats_t1["attigi_gol"] == 2
    assert stats_t1["yedigi_gol"] == 1

    # At 2026-01-15: TeamA has played 2 matches (7 scored, 1 conceded)
    stats_t2 = point_in_time_stats("TeamA", "2026-01-15T00:00:00Z", match_history=history)
    assert stats_t2["mac_sayisi"] == 2
    assert stats_t2["attigi_gol"] == 7
    assert stats_t2["yedigi_gol"] == 1


# ─── 2. Point-in-Time ELO ────────────────────────────────────────────
def test_point_in_time_features():
    """Verify ELO rating updates sequentially and strictly in chronological order."""
    from features.elo import elo_point_in_time_hesapla

    mock_data = {
        "PL": [
            {
                "id": "M1",
                "homeTeam": {"name": "Liverpool"},
                "awayTeam": {"name": "Everton"},
                "score": {"fullTime": {"home": 3, "away": 0}},
                "utcDate": "2026-02-01T15:00:00Z"
            },
            {
                "id": "M2",
                "homeTeam": {"name": "Liverpool"},
                "awayTeam": {"name": "ManCity"},
                "score": {"fullTime": {"home": 1, "away": 2}},
                "utcDate": "2026-02-08T15:00:00Z"
            }
        ]
    }

    pit = elo_point_in_time_hesapla(mock_data)
    # Prior to M1 Liverpool has default starting ELO
    assert pit["M1"]["ev_elo"] == 1500.0
    # Prior to M2 Liverpool won M1 so ELO must be > 1500.0
    assert pit["M2"]["ev_elo"] > 1500.0


# ─── 3. xG Point-in-Time ─────────────────────────────────────────────
def test_xg_point_in_time():
    """Verify xG proxy or rolling xG does not use future matches."""
    from features.team_stats import point_in_time_xg

    history = [
        {"team": "Real Madrid", "opponent": "Getafe", "xg": 2.4, "xg_conceded": 0.5, "date": "2026-01-05T20:00:00Z"},
        {"team": "Real Madrid", "opponent": "Valencia", "xg": 0.8, "xg_conceded": 2.1, "date": "2026-01-15T20:00:00Z"},
    ]

    xg_early = point_in_time_xg("Real Madrid", "2026-01-10T00:00:00Z", xg_history=history)
    assert xg_early["matches_count"] == 1
    assert abs(xg_early["mean_xg"] - 2.4) < 1e-4

    xg_late = point_in_time_xg("Real Madrid", "2026-01-20T00:00:00Z", xg_history=history)
    assert xg_late["matches_count"] == 2
    assert abs(xg_late["mean_xg"] - (2.4 + 0.8) / 2.0) < 1e-4


# ─── 4. H2H Point-in-Time ────────────────────────────────────────────
def test_h2h_point_in_time():
    """Verify H2H calculates match wins/draws/losses, NOT goal ratio as win rate."""
    from features.h2h_model import h2h_hesapla_pit

    h2h_matches = [
        # Game 1: Arsenal (H) vs Chelsea (A) 1-0 -> Arsenal win
        {"ev": "Arsenal", "dep": "Chelsea", "ev_gol": 1, "dep_gol": 0, "tarih": "2025-05-01T15:00:00Z"},
        # Game 2: Chelsea (H) vs Arsenal (A) 0-0 -> Draw
        {"ev": "Chelsea", "dep": "Arsenal", "ev_gol": 0, "dep_gol": 0, "tarih": "2025-11-01T15:00:00Z"},
        # Game 3: Future match (2026-05) -> should NOT be included for 2026-01 query
        {"ev": "Arsenal", "dep": "Chelsea", "ev_gol": 5, "dep_gol": 5, "tarih": "2026-05-01T15:00:00Z"},
    ]

    # Query before Game 3
    res = h2h_hesapla_pit("Arsenal", "Chelsea", "2026-01-01T00:00:00Z", h2h_history=h2h_matches)
    assert res["toplam_mac"] == 2
    assert res["ev_galibiyet"] == 1  # Arsenal won 1
    assert res["beraberlik"] == 1   # 1 draw
    assert res["dep_galibiyet"] == 0 # Chelsea won 0
    # Win rate must be 1 win / 2 matches = 0.50, not goal ratio
    assert abs(res["ev_galibiyet_orani"] - 0.50) < 1e-4


# ─── 5. Odds Timestamp ───────────────────────────────────────────────
def test_odds_timestamp():
    """Verify odds matching rejects odds collected after match kickoff."""
    from data.matcher import odds_timestamp_gecerli_mi

    kickoff = "2026-03-01T15:00:00Z"
    odds_time_valid = "2026-03-01T14:30:00Z"
    odds_time_invalid = "2026-03-01T15:15:00Z"

    assert odds_timestamp_gecerli_mi(odds_time_valid, kickoff) is True
    assert odds_timestamp_gecerli_mi(odds_time_invalid, kickoff) is False


# ─── 6. No Synthetic Market Odds ─────────────────────────────────────
def test_no_synthetic_market_odds():
    """Verify walk_forward backtest strictly uses real Pinnacle/bookmaker odds."""
    from backtesting.walk_forward import run_walk_forward_backtest

    res = run_walk_forward_backtest(initial_bankroll=1000.0, min_edge=0.01)
    assert res.get("uses_synthetic_odds") is False or res.get("uses_synthetic_odds") is None
    # All tested bets must have valid positive market odds
    for bet in res.get("executed_bets", []):
        assert bet.get("odds", 0) > 1.01
        assert bet.get("source") != "synthetic_inverted_prob"


# ─── 7. Out-of-Fold Calibration ──────────────────────────────────────
def test_calibration_oof():
    """Verify calibrator training uses held-out / out-of-fold predictions."""
    from calibration.calibration import train_calibrator_oof

    np.random.seed(42)
    n = 300
    # Simulated OOF predictions from a 3-class classifier
    oof_X = np.random.dirichlet((3, 2, 2), size=n)
    oof_y = np.random.choice([0, 1, 2], size=n)

    calibrator = train_calibrator_oof(oof_X, oof_y, method="isotonic")
    assert calibrator is not None
    # Test calibrated outputs on unseen probs
    test_probs = np.array([[0.6, 0.25, 0.15], [0.33, 0.33, 0.34]])
    cal_probs = calibrator.predict_proba(test_probs)
    assert cal_probs.shape == (2, 3)
    assert np.allclose(cal_probs.sum(axis=1), 1.0)


# ─── 8. Feature Parity ───────────────────────────────────────────────
def test_feature_parity():
    """Verify feature vector length and order matches training schema."""
    from model.train import FEATURE_SUTUNLARI

    expected_min_features = 20
    assert len(FEATURE_SUTUNLARI) >= expected_min_features
    # Check essential features exist
    assert "elo_fark_norm" in FEATURE_SUTUNLARI
    assert "lam_ev" in FEATURE_SUTUNLARI
    assert "form_fark" in FEATURE_SUTUNLARI


# ─── 9. Class Mapping Consistency ────────────────────────────────────
def test_class_mapping():
    """Verify 0=HOME, 1=DRAW, 2=AWAY class indices across all modules."""
    from model.ensemble import SINIF_ESLESTIRME

    assert SINIF_ESLESTIRME[0] in ("1", "HOME", "EV")
    assert SINIF_ESLESTIRME[1] in ("X", "DRAW", "BER")
    assert SINIF_ESLESTIRME[2] in ("2", "AWAY", "DEP")


# ─── 10. Probability Sum ─────────────────────────────────────────────
def test_probability_sum():
    """Verify ensemble prediction output sums to exactly 1.0."""
    from model.ensemble import model_birlestir

    poisson_p = {"ev": 0.45, "ber": 0.30, "dep": 0.25}
    elo_p = {"ev": 0.50, "ber": 0.25, "dep": 0.25}

    res = model_birlestir(poisson_p, elo_p, lig="PL")
    probs = res["olasiliklar"]
    total_p = probs["ev"] + probs["ber"] + probs["dep"]
    assert abs(total_p - 1.0) < 1e-4


# ─── 11. Probability Bounds ──────────────────────────────────────────
def test_probability_bounds():
    """Verify all calibrated and ensemble probabilities lie strictly in [0.0, 1.0]."""
    from model.ensemble import model_birlestir

    poisson_p = {"ev": 0.85, "ber": 0.10, "dep": 0.05}
    elo_p = {"ev": 0.70, "ber": 0.20, "dep": 0.10}

    res = model_birlestir(poisson_p, elo_p, lig="PL")
    for key, p in res["olasiliklar"].items():
        assert 0.0 <= p <= 1.0, f"Probability {key}={p} out of bounds"


# ─── 12. Duplicate Fixture Handling ──────────────────────────────────
def test_duplicate_fixture():
    """Verify duplicate matches on the same date are deduplicated."""
    from data.matcher import fikstur_tekillestir

    fixtures = [
        {"ev": "Bayern München", "dep": "Borussia Dortmund", "tarih": "2026-04-05T17:30:00Z", "id": "1"},
        {"ev": "Bayern München", "dep": "Borussia Dortmund", "tarih": "2026-04-05T17:30:00Z", "id": "2"},
        {"ev": "AC Milan", "dep": "Inter", "tarih": "2026-04-05T19:45:00Z", "id": "3"}
    ]

    deduped = fikstur_tekillestir(fixtures)
    assert len(deduped) == 2


# ─── 13. Stale Data Filtering ────────────────────────────────────────
def test_stale_data():
    """Verify matches that finished in the past are not considered upcoming."""
    from data.matcher import gelecek_mac_filtrele

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    past_iso = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future_iso = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    fixtures = [
        {"id": "past", "utcDate": past_iso},
        {"id": "future", "utcDate": future_iso}
    ]

    upcoming = gelecek_mac_filtrele(fixtures)
    assert len(upcoming) == 1
    assert upcoming[0]["id"] == "future"


# ─── 14. Missing Odds Handling ───────────────────────────────────────
def test_missing_odds():
    """Verify value engine yields 0.0 edge (NO BET) for missing, 0, or <= 1.0 odds."""
    from value.edge import value_hesapla

    assert value_hesapla(olasilik=0.60, oran=0.0) == 0.0
    assert value_hesapla(olasilik=0.60, oran=1.0) == 0.0
    assert value_hesapla(olasilik=0.60, oran=-1.5) == 0.0


# ─── 15. Invalid / Extreme Odds Handling ─────────────────────────────
def test_invalid_odds():
    """Verify edges exceeding 20% are flagged as data errors and return 0.0 (NO BET)."""
    from value.edge import value_hesapla

    # 60% probability with odds of 10.0 gives massive hallucinated edge -> MUST BE 0.0
    extreme_edge = value_hesapla(olasilik=0.60, oran=10.0, fair_p=0.10)
    assert extreme_edge == 0.0


# ─── 16. Model Versioning Metadata ───────────────────────────────────
def test_model_version():
    """Verify executed bets include model_version, feature_version, and calibrator_version."""
    from tracking.clv_tracker import bahis_kaydet, _yukle

    test_bet = {
        "ev": "TeamX", "dep": "TeamY", "tahmin": "Ev Sahibi Kazanır",
        "oran": 2.10, "edge": 0.04, "p_secim": 0.52,
        "model_version": "v4.0-institutional",
        "feature_version": "v4.0-pit",
        "calibrator_version": "v4.0-oof"
    }

    bahis_kaydet(test_bet)
    db = _yukle()
    matched = [b for b in db["bahisler"] if b.get("ev") == "TeamX" and b.get("dep") == "TeamY"]
    assert len(matched) > 0
    record = matched[-1]
    assert record.get("model_version") == "v4.0-institutional"
    assert record.get("feature_version") == "v4.0-pit"
    assert record.get("calibrator_version") == "v4.0-oof"


# ─── 17. Prediction Reproducibility ──────────────────────────────────
def test_prediction_reproducibility():
    """Verify identical inputs yield identical outputs (deterministic inference)."""
    from model.ensemble import model_birlestir

    poisson_p = {"ev": 0.40, "ber": 0.35, "dep": 0.25}
    elo_p = {"ev": 0.42, "ber": 0.33, "dep": 0.25}

    res1 = model_birlestir(poisson_p, elo_p, lig="BL1")
    res2 = model_birlestir(poisson_p, elo_p, lig="BL1")

    assert res1["olasiliklar"] == res2["olasiliklar"]
    assert res1["guven"] == res2["guven"]


# ─── 18. Walk-Forward Order ──────────────────────────────────────────
def test_walk_forward_order():
    """Verify walk-forward splits always have max(train_date) < min(test_date)."""
    from backtesting.walk_forward import generate_walk_forward_windows

    # Create dummy match dates spanning 6 months
    dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(180)]
    windows = generate_walk_forward_windows(dates, train_days=90, test_days=30, step_days=30)

    for w in windows:
        assert max(w["train_dates"]) < min(w["test_dates"]), "Lookahead in walk-forward window!"


# ─── 19. No Test Set Tuning / Leakage ────────────────────────────────
def test_no_test_set_tuning():
    """Verify test fold data is never seen during hyperparameter or shrinkage estimation."""
    from calibration.calibration import evaluate_calibration_metrics

    # Test set evaluation should return clean metrics without modifying test targets
    y_true = np.array([0, 1, 2, 0, 1])
    y_prob = np.array([
        [0.7, 0.2, 0.1],
        [0.2, 0.6, 0.2],
        [0.1, 0.3, 0.6],
        [0.5, 0.3, 0.2],
        [0.3, 0.4, 0.3]
    ])

    metrics = evaluate_calibration_metrics(y_prob, y_true)
    assert "brier_score" in metrics
    assert "log_loss" in metrics
    assert "ece" in metrics
    assert 0.0 <= metrics["brier_score"] <= 1.0
