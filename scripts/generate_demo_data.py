from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pulseiq.data import DEMO_DATA_PATH, generate_demo_data


def main() -> None:
    DEMO_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    df = generate_demo_data(rows=5000, seed=42)
    df.to_csv(DEMO_DATA_PATH, index=False)
    print(f"Wrote {len(df):,} rows to {DEMO_DATA_PATH}")


if __name__ == "__main__":
    main()
