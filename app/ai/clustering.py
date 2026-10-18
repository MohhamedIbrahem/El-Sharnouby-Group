"""
K-Means Customer Clustering & RFM Segmentation Module.
Segments customers into actionable business cohorts.
"""
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from app.core.logger import setup_logger, log_function

logger = setup_logger(__name__)

@log_function
def compute_rfm_scores(sales_df: pd.DataFrame) -> pd.DataFrame:
    """Computes Recency, Frequency, and Monetary scores per customer."""
    if sales_df.empty or "Customer_ID" not in sales_df.columns:
        return pd.DataFrame()

    ref_date = sales_df["Order_Date"].max() if "Order_Date" in sales_df.columns else pd.Timestamp.now()

    rfm = sales_df.groupby("Customer_ID").agg(
        Last_Order=("Order_Date", "max") if "Order_Date" in sales_df.columns else ("Invoice_ID", "count"),
        Frequency=("Invoice_ID", "nunique") if "Invoice_ID" in sales_df.columns else ("Net_Sales_EGP", "count"),
        Monetary=("Net_Sales_EGP", "sum") if "Net_Sales_EGP" in sales_df.columns else ("Quantity", "sum")
    ).reset_index()

    if "Order_Date" in sales_df.columns:
        rfm["Recency"] = (ref_date - rfm["Last_Order"]).dt.days
    else:
        rfm["Recency"] = 30

    return rfm

@log_function
def segment_customers_kmeans(rfm_df: pd.DataFrame, n_clusters: int = 4) -> pd.DataFrame:
    """Segments customers using K-Means and assigns Arabic persona names."""
    if rfm_df.empty or len(rfm_df) < n_clusters:
        return rfm_df

    features = ["Recency", "Frequency", "Monetary"]
    X = rfm_df[features].fillna(0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    rfm_df["Cluster"] = kmeans.fit_predict(X_scaled)

    cluster_means = rfm_df.groupby("Cluster").agg(
        mean_m=("Monetary", "mean"),
        mean_f=("Frequency", "mean"),
        mean_r=("Recency", "mean")
    )
    cluster_means["Score"] = (
        cluster_means["mean_m"] / (cluster_means["mean_m"].max() + 1) +
        cluster_means["mean_f"] / (cluster_means["mean_f"].max() + 1) -
        cluster_means["mean_r"] / (cluster_means["mean_r"].max() + 1)
    )
    ranked = cluster_means["Score"].sort_values(ascending=False).index.tolist()

    segment_names = [
        "Champions",
        "Loyal Customers",
        "At Risk",
        "Lost",
    ]
    mapping = {ranked[i]: segment_names[i] for i in range(min(n_clusters, len(segment_names)))}
    rfm_df["Segment"] = rfm_df["Cluster"].map(mapping).fillna("New customers")

    return rfm_df
