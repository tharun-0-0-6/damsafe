import pandas as pd
import numpy as np
import os
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import classification_report, accuracy_score

# CONFIG
PROJECT_DIR = r"F:\STUDY\Sem 6\CIP\Damsafe"
INPUT_CSV = os.path.join(PROJECT_DIR, "data", "training_dataset_ml.csv")
MODEL_DIR = os.path.join(PROJECT_DIR, "models")
MODEL_OUT = os.path.join(MODEL_DIR, "dam_state_rf.joblib")

os.makedirs(MODEL_DIR, exist_ok=True)

# Feature list used for training
FEATURES = [
    "Measured_PPV_mm_per_s", 
    "Distance_from_Dam_m", 
    "SDI", 
    "Charge_Factor", 
    "BVII", 
    "RDI", 
    "Slope_deg", 
    "Burden_m", 
    "Spacing_m", 
    "Total_Explosive_Quantity_kg"
]

TARGET = "Dam_State_ID"

def train_model():
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Error: {INPUT_CSV} not found. Run the generation script first.")
        return

    print(f"Loading dataset: {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    
    X = df[FEATURES]
    y = df[TARGET]
    
    # Split: 80% train, 20% test
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    print(f"Training Random Forest Classifier with GridSearchCV...")
    rf = RandomForestClassifier(random_state=42)
    
    # Define hyperparameter grid to search
    param_grid = {
        'n_estimators': [50, 100, 200],
        'max_depth': [None, 10, 20],
        'min_samples_split': [2, 5, 10],
        'min_samples_leaf': [1, 2, 4]
    }
    
    # Apply 5-Fold Cross Validation
    grid_search = GridSearchCV(estimator=rf, param_grid=param_grid, cv=5, n_jobs=-1, scoring='accuracy', verbose=1)
    grid_search.fit(X_train, y_train)
    
    print("\nBest Hyperparameters Found:")
    print(grid_search.best_params_)
    print(f"Best CV Accuracy: {grid_search.best_score_:.4f}")
    
    # Extract the absolute best model found during tuning
    best_model = grid_search.best_estimator_
    
    # Evaluation on the withheld Test Set
    y_pred = best_model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    print("\nTraining Complete!")
    print(f"Test Accuracy: {acc:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["Intact", "Damaged", "Failed"]))
    
    # Feature Importance from the best model
    print("\nFeature Importance:")
    importance = pd.Series(best_model.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print(importance)
    
    # Save the optimized model
    joblib.dump(best_model, MODEL_OUT)
    print(f"\nModel saved to: {MODEL_OUT}")

if __name__ == "__main__":
    train_model()
