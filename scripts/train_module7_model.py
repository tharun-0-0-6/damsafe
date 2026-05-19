import pandas as pd
import numpy as np
import os
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

# CONFIG
PROJECT_DIR = r"F:\STUDY\Sem 6\CIP\Damsafe"
INPUT_CSV = os.path.join(PROJECT_DIR, "data", "training_dataset_m7_ml.csv")
MODEL_DIR = os.path.join(PROJECT_DIR, "models")
MODEL_OUT = os.path.join(MODEL_DIR, "module7_recommender_rf.joblib")

os.makedirs(MODEL_DIR, exist_ok=True)

# Input features describing the failed blast
FEATURES_X = [
    "Measured_PPV_mm_per_s", 
    "Distance_from_Dam_m", 
    "Charge_Factor", 
    "Total_Explosive_Quantity_kg", 
    "SDI", 
    "BVII", 
    "RDI", 
    "Slope_deg", 
    "Burden_m", 
    "Spacing_m", 
    "Severity_Ratio"
]

# The ideal, physically calculated safety recommendations
TARGETS_Y = [
    "Rec_Target_PPV_mm_per_s", 
    "Rec_Distance_from_Dam_m", 
    "Rec_Charge_Factor", 
    "Rec_Burden_m", 
    "Rec_Spacing_m"
]

def train_m7_recommender():
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Error: {INPUT_CSV} not found. Run generate_training_data_m7.py first.")
        return

    print(f"Loading M7 training dataset: {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    
    # Check if necessary columns exist
    missing = [c for c in FEATURES_X + TARGETS_Y if c not in df.columns]
    if missing:
         print(f"❌ Missing columns in dataset: {missing}")
         return
         
    X = df[FEATURES_X]
    y = df[TARGETS_Y]
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print(f"Training Multi-Output Random Forest Regressor (Module 7)...")
    model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    print("\nTraining Complete! Evaluating on Test Set...")
    y_pred = model.predict(X_test)
    
    mae = mean_absolute_error(y_test, y_pred, multioutput='raw_values')
    r2 = r2_score(y_test, y_pred, multioutput='raw_values')
    
    print(f"\n--- Evaluation Metrics per Target ---")
    for i, target in enumerate(TARGETS_Y):
        print(f"{target}:")
        print(f"  R2 Score: {r2[i]:.4f} (Closer to 1 is better)")
        print(f"  Mean Absolute Error: {mae[i]:.4f}")
    
    # Save the optimized model
    joblib.dump(model, MODEL_OUT)
    print(f"\n✅ Module 7 Recommender Model saved to: {MODEL_OUT}")

if __name__ == "__main__":
    train_m7_recommender()
