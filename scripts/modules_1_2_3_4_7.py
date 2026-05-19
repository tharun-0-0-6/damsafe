import os
import time
import random
import numpy as np
import pandas as pd
import joblib

PROJECT_DIR = r"F:\STUDY\Sem 6\CIP\Damsafe"
CSV_PATH = os.path.join(PROJECT_DIR, "data", "input_dataset.csv")
OUT_DIR = os.path.join(PROJECT_DIR, "outputs", "tables")
os.makedirs(OUT_DIR, exist_ok=True)

OUT_CSV = os.path.join(OUT_DIR, "output_modules_1_2_3_4_7.csv")
MODEL_PATH = os.path.join(PROJECT_DIR, "models", "dam_state_rf.joblib")

#Bhavani sagar Dam
DAM_LAT = 11.471203137436701   # Latitude of the dam
DAM_LON = 77.1133697444026   # Longitude of the dam

#Vaniyar Dam
#DAM_LAT = 11.902253105901455   # Latitude of the dam
#DAM_LON = 78.33066446636784203137436701   # Longitude of the dam

# Module 1 (BVII): PPV + Distance + (optional) Charge_Factor
W_PPV = 0.65
W_DIST = 0.25
W_CHARGE = 0.10

# Module 2 (SDI): accumulation factor
SDI_GAIN = 1.0  # scale factor on accumulation

# Module 3 (RDI): PPV + Distance + (optional) Slope
W_RDI_PPV = 0.60
W_RDI_DIST = 0.25
W_RDI_SLOPE = 0.15

# If you don't have slope per blast yet, use a constant (degrees) 
DEFAULT_SLOPE_DEG = 10.0

# HELPERS
def minmax(series: pd.Series, clip=True) -> pd.Series:
    """Min-max normalize to 0..1 safely."""
    s = series.astype(float)
    mn, mx = np.nanmin(s), np.nanmax(s)
    if mx - mn == 0:
        out = pd.Series(np.zeros(len(s)), index=s.index)
    else:
        out = (s - mn) / (mx - mn)
    return out.clip(0, 1) if clip else out


def inv_distance_norm(dist_m: pd.Series) -> pd.Series:
    """Convert distance to 'risk' (closer = higher), normalized 0..1."""
    d_norm = minmax(dist_m)
    return 1.0 - d_norm


def haversine_distance_m(lat1, lon1, lat2_series: pd.Series, lon2_series: pd.Series) -> pd.Series:
    """Compute great-circle distance in metres from a fixed dam point to each blast coordinate."""
    R = 6_371_000  # Earth radius in metres
    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2_series.astype(float))
    dlat = lat2_r - lat1_r
    dlon = np.radians(lon2_series.astype(float)) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


def run_once():
    """Run Modules 1, 2, 3, 4, 7 once for the current CSV."""
    df = pd.read_csv(CSV_PATH)

    # --- Auto-compute distance from dam coordinates if blast coords are present ---
    lon_col = next((c for c in ["Blast_lon", "Blast_Lon", "Blast_Longitude"] if c in df.columns), None)
    lat_col = next((c for c in ["Blast_lat", "Blast_Lat", "Blast_Latitude"] if c in df.columns), None)

    if lon_col and lat_col:
        df["Distance_from_Dam_m"] = haversine_distance_m(
            DAM_LAT, DAM_LON, df[lat_col], df[lon_col]
        )
        print(f"Distance_from_Dam_m auto-computed from dam coordinates ({DAM_LAT}, {DAM_LON}).")
    elif "Distance_from_Dam_m" not in df.columns:
        raise ValueError(
            "CSV must have 'Distance_from_Dam_m' OR blast coordinate columns (Blast_lat/Blast_lon). "
            f"Neither found. Set DAM_LAT/DAM_LON in config and ensure your CSV has blast coordinates."
        )

    required = ["Measured_PPV_mm_per_s", "Distance_from_Dam_m", "Time"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    has_charge = "Charge_Factor" in df.columns
    has_slope = "Slope_deg" in df.columns


    if not has_slope:
        df["Slope_deg"] = DEFAULT_SLOPE_DEG

    # MODULE 1: BVII
    ppv_n = minmax(df["Measured_PPV_mm_per_s"])
    dist_risk = inv_distance_norm(df["Distance_from_Dam_m"])

    if has_charge:
        charge_n = minmax(df["Charge_Factor"])
    else:
        charge_n = 0.0

    df["BVII"] = (W_PPV * ppv_n) + (W_DIST * dist_risk) + (W_CHARGE * charge_n)

    df["BVII_Level"] = pd.cut(
        df["BVII"],
        bins=[-0.01, 0.33, 0.66, 1.01],
        labels=["Low", "Moderate", "High"],
    )

    # MODULE 2: SDI

    df = df.sort_values("Time").reset_index(drop=True)

    time_parsed = pd.to_datetime(df["Time"], errors="coerce")

    if time_parsed.isna().all():
        # Fall back to numeric time differences if Time is numeric-like
        t_numeric = pd.to_numeric(df["Time"], errors="coerce")
        if t_numeric.isna().all():
            # Last resort: treat blasts as equally spaced
            df["Delta_t"] = 1.0
        else:
            t_numeric = t_numeric.ffill().bfill()
            df["Delta_t"] = t_numeric.diff().fillna(0).clip(lower=0)
    else:
        time_parsed = time_parsed.ffill().bfill()
        df["Delta_t"] = time_parsed.diff().dt.total_seconds().fillna(0).clip(lower=0)

    # SDI(t) = SDI(t-1) + SDI_GAIN * BVII(t) * Delta_t
    df["SDI"] = (SDI_GAIN * df["BVII"] * df["Delta_t"]).cumsum()

    # MODULE 3: RDI (rock mass disturbance)
    slope_n = minmax(df["Slope_deg"])
    df["RDI"] = (W_RDI_PPV * ppv_n) + (W_RDI_DIST * dist_risk) + (W_RDI_SLOPE * slope_n)

    df["RDI_Level"] = pd.cut(
        df["RDI"],
        bins=[-0.01, 0.33, 0.66, 1.01],
        labels=["Low", "Moderate", "High"],
    )

    # MODULE 4: Machine Learning (Random Forest)
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Trained model not found at {MODEL_PATH}. Please run training script first.")

    # Re-extract for later modules
    ppv = df["Measured_PPV_mm_per_s"].astype(float)
    dist = df["Distance_from_Dam_m"].astype(float)

    # Prepare features for the model and ensure any missing optional features are filled safely
    features_list = [
        "Measured_PPV_mm_per_s", "Distance_from_Dam_m", "SDI", "Charge_Factor", 
        "BVII", "RDI", "Slope_deg", "Burden_m", "Spacing_m", "Total_Explosive_Quantity_kg"
    ]
    
    # Create a copy with defaults for missing columns
    X_ml = df.copy()
    for col in features_list:
        if col not in X_ml.columns:
            X_ml[col] = 0.0

    print(f"Predicting Dam State using Random Forest (Module 4)...")
    clf = joblib.load(MODEL_PATH)
    preds = clf.predict(X_ml[features_list])
    
    # Map back to labels
    id_to_label = {0: "Intact", 1: "Damaged", 2: "Failed"}
    df["Dam_State_M4"] = [id_to_label[p] for p in preds]
    df["Failure_Flag_M4"] = df["Dam_State_M4"].apply(lambda x: 1 if x == "Failed" else 0)

    # MODULE 7: Machine Learning Recommender for Failed rows
    M7_MODEL_PATH = os.path.join(PROJECT_DIR, "models", "module7_recommender_rf.joblib")
    if not os.path.exists(M7_MODEL_PATH):
        raise FileNotFoundError(f"Trained M7 model not found at {M7_MODEL_PATH}. Please run train_module7_model.py")

    SAFE_PPV_LIMIT = 5.0

    # Initialize recommendation columns with NaN
    rec_cols = [
        "Rec_Target_PPV_mm_per_s", "Rec_Distance_from_Dam_m", 
        "Rec_Charge_Factor", "Rec_Burden_m", "Rec_Spacing_m"
    ]
    for col in rec_cols:
        df[col] = np.nan

    failed_mask = df["Dam_State_M4"] == "Failed"
    
    if failed_mask.any():
        print(f"Predicting M7 Recommendations for {failed_mask.sum()} failed points using ML...")
        m7_clf = joblib.load(M7_MODEL_PATH)
        
        # Prepare inputs for M7 Regressor
        X_m7 = X_ml.copy()
        
        # Calculate exactly how badly the blast failed
        X_m7["Severity_Ratio"] = np.maximum(X_m7["Measured_PPV_mm_per_s"] / SAFE_PPV_LIMIT, 1.01)
        
        m7_features = [
            "Measured_PPV_mm_per_s", "Distance_from_Dam_m", "Charge_Factor", 
            "Total_Explosive_Quantity_kg", "SDI", "BVII", "RDI", 
            "Slope_deg", "Burden_m", "Spacing_m", "Severity_Ratio"
        ]
        
        # Ensure all columns exist, falling back to 0.0 if missing
        for col in m7_features:
            if col not in X_m7.columns:
                X_m7[col] = 0.0
                
        # ML Inference: Predict 5 continuous variables at once
        preds_m7 = m7_clf.predict(X_m7.loc[failed_mask, m7_features])
        
        # Round the predictions and assign back to dataframe
        preds_rounded = np.round(preds_m7, 2)
        
        df.loc[failed_mask, "Rec_Target_PPV_mm_per_s"] = preds_rounded[:, 0]
        df.loc[failed_mask, "Rec_Distance_from_Dam_m"] = preds_rounded[:, 1]
        df.loc[failed_mask, "Rec_Charge_Factor"] = preds_rounded[:, 2]
        df.loc[failed_mask, "Rec_Burden_m"] = preds_rounded[:, 3]
        df.loc[failed_mask, "Rec_Spacing_m"] = preds_rounded[:, 4]

    # Add X and Y columns for QGIS (longitude and latitude)
    lon_col = "Blast_lon" if "Blast_lon" in df.columns else "Blast_Lon"
    lat_col = "Blast_lat" if "Blast_lat" in df.columns else "Blast_Lat"
    if lon_col in df.columns and lat_col in df.columns:
        df["X"] = pd.to_numeric(df[lon_col], errors="coerce")
        df["Y"] = pd.to_numeric(df[lat_col], errors="coerce")

    # Drop columns not required in output
    cols_to_drop = ["Structural_Output", "Line_Adjusted_Bearing_Deg", "Slope_deg", "Delta_t"]
    for c in cols_to_drop:
        if c in df.columns:
            df = df.drop(columns=[c])

    # At this point df has all inputs + Modules 1–4–7 + recommendations.
    print("Modules 1-4-7 computed for full dataset in memory.")
    return df


if __name__ == "__main__":
    # Always start fresh by deleting the previous session's output
    if os.path.exists(OUT_CSV):
        os.remove(OUT_CSV)
        print(f"Deleted old session output: {OUT_CSV}")

    # Compute all modules once for the current dataset (in memory).
    df_full = run_once()
    total_rows = len(df_full)

    # Pick a random starting index
    start_idx = random.randint(0, total_rows - 1)
    print(f"Starting from random row index {start_idx} (of {total_rows} total rows)")

    # Stream one row per second, appending one row at a time.
    INTERVAL_SECONDS = 1 

    print(
        f"Starting streaming: appending rows from '{CSV_PATH}' to '{OUT_CSV}'. Press Ctrl+C to stop."
    )
    try:
        i = start_idx
        while True:
            row = df_full.iloc[i]
            
            # Check if we need to write the header (only for the first row)
            header_needed = not os.path.exists(OUT_CSV)
            
            # Append the row instead of overwriting
            row.to_frame().T.to_csv(OUT_CSV, mode='a', index=False, header=header_needed)
            
            i = (i + 1) % total_rows  # wrap around
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopping streaming run.")

