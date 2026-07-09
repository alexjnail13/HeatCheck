"""
Win probability inference module.

Loads the trained logistic regression model and scaler once at startup,
then exposes a predict function for real-time win probability calculations.
"""

import numpy as np
import joblib
from pathlib import Path

# ---------- paths to saved model artifacts ----------
MODEL_DIR = Path(__file__).parent  # backend/app/ml/
MODEL_PATH = MODEL_DIR / "win_probability_model.pkl"
SCALER_PATH = MODEL_DIR / "scaler.pkl"

# ---------- module-level storage (loaded once) ----------
_model = None
_scaler = None


def load_model() -> None:
    """
    Load the trained model and scaler from disk into module-level variables.
    Called once at app startup — not on every prediction.

    Raises:
        FileNotFoundError: If model or scaler .pkl files are missing.
    """
    global _model, _scaler

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")
    if not SCALER_PATH.exists():
        raise FileNotFoundError(f"Scaler file not found: {SCALER_PATH}")

    _model = joblib.load(MODEL_PATH)
    _scaler = joblib.load(SCALER_PATH)


def predict_win_probability(
    point_differential: float,
    time_remaining_seconds: float,
    team_strength_diff: float,
) -> float:
    """
    Predict the home team's win probability given current game state.

    Args:
        point_differential: home_score - away_score (positive = home leading)
        time_remaining_seconds: seconds left in the game
        team_strength_diff: home_win_pct - away_win_pct

    Returns:
        Float between 0.0 and 1.0 representing home team win probability.

    Raises:
        RuntimeError: If model hasn't been loaded yet.
        ValueError: If time_remaining_seconds is negative.
    """
    if _model is None or _scaler is None:
        raise RuntimeError("Model not loaded. Call load_model() first.")

    if time_remaining_seconds < 0:
        raise ValueError("time_remaining_seconds cannot be negative.")

    # Step 1: Compute the interaction feature
    lead_safety = point_differential / (time_remaining_seconds + 1)

    # Step 2: Arrange all 4 features and scale them
    features = np.array([[
        point_differential,
        time_remaining_seconds,
        team_strength_diff,
        lead_safety,
    ]])
    scaled_features = _scaler.transform(features)

    # Step 3: Get probability from the model
    # predict_proba returns [[prob_class_0, prob_class_1]]
    # class 1 = home team wins, so we grab index [0][1]
    probabilities = _model.predict_proba(scaled_features)
    home_win_prob = probabilities[0][1]

    return round(float(home_win_prob), 4)