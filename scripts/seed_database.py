"""Create (or recreate) the InsightSQL database with deterministic sample data.

Usage:
    python scripts/seed_database.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, database  # noqa: E402


def main() -> None:
    db_path = config.get_db_path()
    database.seed_sample_data(db_path)
    conn = database.connect(db_path)
    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    conn.close()
    print(f"Seeded {db_path}: {products} products, {sales} sales.")


if __name__ == "__main__":
    main()
