import sys
sys.path.insert(0, "scripts")
from modules_1_2_3_4_7 import run_once
df = run_once()
f = df[df["Dam_State_M4"] == "Failed"]
print("\nSample Failed rows:")
for i, r in f.head(5).iterrows():
    ppv = r["Measured_PPV_mm_per_s"]
    dist = r["Distance_from_Dam_m"]
    rd = r["Rec_Distance_from_Dam_m"]
    rp = r["Rec_Target_PPV_mm_per_s"]
    rb = r.get("Rec_Burden_m", 0)
    print(f"  PPV={ppv:.2f}  Dist={dist:.0f}  ->  RecDist={rd:.0f}  RecPPV={rp:.2f}  RecBurden={rb:.2f}")
print("\nStates:", df["Dam_State_M4"].value_counts().to_dict())
