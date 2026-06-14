#!/usr/bin/env python3
"""Generate labels.parquet from the IMDB test set.

Requires: pip install datasets pandas pyarrow

Usage:
    python generate_labels.py

Output: labels.parquet  (25000 rows, columns: id, label)
"""

import pandas as pd
from datasets import load_dataset

dataset = load_dataset("stanfordnlp/imdb", split="test")
labels = dataset["label"]

df = pd.DataFrame({
    "id": list(range(len(labels))),
    "label": labels,
})
df.to_parquet("labels.parquet", index=False)

print(f"Created labels.parquet with {len(df)} rows")
print(f"Label distribution:\n{df['label'].value_counts().to_string()}")
