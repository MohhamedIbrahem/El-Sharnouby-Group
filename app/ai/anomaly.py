"""
AI Cross-Department Anomaly Detection Engine (Task 15)

Uses Isolation Forest unsupervised machine learning to detect products
experiencing multi-department operational stress (QC defects, rework, returns,
production delays, and inventory stagnation).
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest

from app.core.logger import setup_logger, log_function

logger = setup_logger(__name__)


@log_function
def detect_cross_department_anomalies(
    product_metrics_df: pd.DataFrame,
    contamination: float = 0.15,
    random_state: int = 42
) -> pd.DataFrame:
    """
    Runs Isolation Forest on cross-department product metrics.
    
    Args:
        product_metrics_df: DataFrame containing per-product multi-department metrics:
            - apparent_margin_pct
            - true_margin_pct
            - margin_erosion_pct
            - qc_loss
            - print_rework
            - refunds
            - delay_days
            - overtime_hours
            
    Returns:
        DataFrame augmented with:
            - is_anomalous (bool): True if flagged as outlier
            - anomaly_score (float): Normalized severity score (0 to 1)
            - primary_stress (str): Arabic description of primary stress driver
    """
    df = product_metrics_df.copy()
    if df.empty or len(df) < 5:
        df["is_anomalous"] = False
        df["anomaly_score"] = 0.0
        df["primary_stress"] = "Normal"
        return df

    feature_cols = [
        "apparent_margin_pct", "true_margin_pct", "margin_erosion_pct",
        "qc_loss", "print_rework", "refunds", "delay_days", "overtime_hours"
    ]
    
    # Ensure all feature columns exist and are clean
    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    X = df[feature_cols].values

    # Train Isolation Forest
    iso = IsolationForest(
        contamination=contamination,
        random_state=random_state,
        n_estimators=100
    )
    
    predictions = iso.fit_predict(X)
    raw_scores = -iso.score_samples(X)  # Higher score = more anomalous

    # Normalize scores to 0-1 range
    min_s, max_s = raw_scores.min(), raw_scores.max()
    norm_scores = (raw_scores - min_s) / (max_s - min_s + 1e-9)

    df["is_anomalous"] = predictions == -1
    df["anomaly_score"] = np.round(norm_scores, 3)

    # Determine primary stress driver in Arabic
    primary_stresses = []
    for _, row in df.iterrows():
        stresses = []
        if row["margin_erosion_pct"] > 8.0:
            stresses.append("Severe margin erosion")
        if row["qc_loss"] > df["qc_loss"].quantile(0.80):
            stresses.append("Quality inspection losses")
        if row["refunds"] > df["refunds"].quantile(0.80):
            stresses.append("High customer returns")
        if row["print_rework"] > df["print_rework"].quantile(0.80):
            stresses.append("Printing waste & rework")
        if row["delay_days"] > df["delay_days"].quantile(0.80):
            stresses.append("Production line delays")
        
        if not stresses:
            stresses.append("Stable & compliant")
        primary_stresses.append(" • ".join(stresses[:2]))

    df["primary_stress"] = primary_stresses
    return df
