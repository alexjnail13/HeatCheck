"""
Train a logistic regression model to predict NBA win probability.

Features:
    - point_differential   (home score - away score at that moment)
    - time_remaining_seconds (total seconds left in regulation)
    - team_strength_diff   (home win% - away win%)

Label:
    - home_team_won        (1 if home team won, 0 if not)

Usage:
    python -m app.ml.train
"""

import os
import logging

import pandas as pd
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, log_loss, classification_report
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "training_data.csv")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "ml", "win_probability_model.pkl")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "..", "ml", "scaler.pkl")

FEATURE_COLUMNS = [
    "point_differential",
    "time_remaining_seconds",
    "team_strength_diff",
]
LABEL_COLUMN = "home_team_won"

TEST_SIZE = 0.2        # 80/20 split
RANDOM_STATE = 42      # for reproducible results

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


def main():
    # --- Step 1: Load the CSV --------------------------------------------
    logger.info(f"Loading training data from {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    logger.info(f"Loaded {len(df)} rows with columns: {list(df.columns)}")

    # Drop any rows with missing values in our feature/label columns
    df = df.dropna(subset=FEATURE_COLUMNS + [LABEL_COLUMN])
    logger.info(f"After dropping nulls: {len(df)} rows")

    # Creating a new lead safety column
    df["lead_safety"] = df["point_differential"] / (df["time_remaining_seconds"] + 1)  # add 1 to avoid division by zero
    FEATURE_COLUMNS.append("lead_safety")

    # --- Step 2: Separate features (X) from label (y) --------------------
    X = df[FEATURE_COLUMNS]
    y = df[LABEL_COLUMN]

    logger.info(f"Features shape: {X.shape}")
    logger.info(f"Label distribution:\n{y.value_counts()}")

    # --- Step 3: Split into train/test (80/20) ---------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
    )
    logger.info(f"Training set: {len(X_train)} rows")
    logger.info(f"Test set:     {len(X_test)} rows")

    # --- Step 3b: Scale features (fix the scale problem!) ----------------
    # Fit scaler on training data ONLY, then transform both sets
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)   # fit + transform training
    X_test_scaled = scaler.transform(X_test)          # transform only on test

    logger.info("Feature scaling applied (StandardScaler)")
    logger.info(f"  Means:  {dict(zip(FEATURE_COLUMNS, scaler.mean_))}")
    logger.info(f"  Stdevs: {dict(zip(FEATURE_COLUMNS, scaler.scale_))}")

    # --- Step 4: Train the model -----------------------------------------
    logger.info("Training logistic regression model...")
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train_scaled, y_train)
    logger.info("Training complete!")

    # --- Step 5: Evaluate on test set ------------------------------------
    # Hard predictions (0 or 1)
    y_pred = model.predict(X_test_scaled)
    accuracy = accuracy_score(y_test, y_pred)
    logger.info(f"Accuracy: {accuracy:.4f} ({accuracy * 100:.1f}%)")

    # Probability predictions (0.0 to 1.0)
    y_prob = model.predict_proba(X_test_scaled)[:, 1]  # probability of class 1 (home win)
    logloss = log_loss(y_test, y_prob)
    logger.info(f"Log Loss: {logloss:.4f}")

    # Detailed breakdown
    logger.info(f"\nClassification Report:\n{classification_report(y_test, y_pred)}")

    # --- Step 6: Inspect the model (what did it learn?) ------------------
    logger.info("Model coefficients (what the model learned):")
    for feature, coef in zip(FEATURE_COLUMNS, model.coef_[0]):
        logger.info(f"  {feature}: {coef:.4f}")
    logger.info(f"  intercept: {model.intercept_[0]:.4f}")

    # --- Step 7: Save the trained model AND scaler ------------------------
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    logger.info(f"Model saved to {MODEL_PATH}")
    logger.info(f"Scaler saved to {SCALER_PATH}")

    # --- Step 8: Quick sanity check — test some game scenarios -----------
    logger.info("\n--- Sanity Check: Sample Predictions ---")
    test_scenarios = [
        {"point_differential": 0, "time_remaining_seconds": 2880, "team_strength_diff": 0.0, "lead_safety": 0.0},
        {"point_differential": 10, "time_remaining_seconds": 300, "team_strength_diff": 0.0, "lead_safety": 10 / (300 + 1)},
        {"point_differential": -10, "time_remaining_seconds": 300, "team_strength_diff": 0.0, "lead_safety": -10 / (300 + 1)},
        {"point_differential": 3, "time_remaining_seconds": 30, "team_strength_diff": 0.0, "lead_safety": 3 / (30 + 1)},
        {"point_differential": 20, "time_remaining_seconds": 60, "team_strength_diff": 0.0, "lead_safety": 20 / (60 + 1)},
        {"point_differential": 0, "time_remaining_seconds": 2880, "team_strength_diff": 0.3, "lead_safety": 0.0},
    ]
    descriptions = [
        "Tied game, start of game, equal teams",
        "Home up 10, 5 min left, equal teams",
        "Home down 10, 5 min left, equal teams",
        "Home up 3, 30 sec left, equal teams",
        "Home up 20, 1 min left, equal teams",
        "Tied game, start of game, home team much stronger",
    ]

    for scenario, desc in zip(test_scenarios, descriptions):
        scenario_df = pd.DataFrame([scenario])
        scenario_scaled = scaler.transform(scenario_df)  # must scale before predicting!
        prob = model.predict_proba(scenario_scaled)[0][1]
        logger.info(f"  {desc}")
        logger.info(f"    → Home win probability: {prob:.1%}")


if __name__ == "__main__":
    main()