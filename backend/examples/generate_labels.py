#!/usr/bin/env python3
"""Generate labels.parquet ground truth for binary sentiment classification.

Usage:
    python generate_labels.py

Output: labels.parquet  (500 rows, columns: id, label)
"""

import pandas as pd
import numpy as np

np.random.seed(42)
n = 500

df = pd.DataFrame({
    "id": np.arange(1, n + 1),
    "label": np.random.choice([0, 1], size=n),
})

df.to_parquet("labels.parquet", index=False)

print(f"Created labels.parquet with {len(df)} rows")
print("\nFirst 5 rows:")
print(df.head())
print("\nLabel distribution:")
print(df["label"].value_counts().to_string())
