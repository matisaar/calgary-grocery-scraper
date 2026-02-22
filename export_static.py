"""
Export the SQLite database to static JSON files for GitHub Pages.
Run this after scraping to update the static site data:
    python export_static.py
"""

import json
import os
import sqlite3
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "grocery_prices.db")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
DOCS_DATA = os.path.join(DOCS_DIR, "data")


def export():
    os.makedirs(DOCS_DATA, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── All products (compact: only fields the static site needs) ──
    rows = conn.execute("""
        SELECT product_name, brand, price, regular_price, unit_price, unit,
               size, category, store, url, image_url, on_sale
        FROM products
        WHERE price IS NOT NULL
        ORDER BY product_name, price ASC
    """).fetchall()

    products = []
    for r in rows:
        p = {
            "n": r["product_name"] or "",
            "b": r["brand"] or "",
            "p": r["price"],
            "s": r["store"] or "",
            "cat": r["category"] or "",
        }
        if r["regular_price"]:
            p["rp"] = r["regular_price"]
        if r["size"]:
            p["sz"] = r["size"]
        if r["unit_price"]:
            p["up"] = r["unit_price"]
        if r["unit"]:
            p["u"] = r["unit"]
        if r["url"]:
            p["url"] = r["url"]
        if r["image_url"]:
            p["img"] = r["image_url"]
        if r["on_sale"]:
            p["sale"] = 1
        products.append(p)

    with open(os.path.join(DOCS_DATA, "products.json"), "w", encoding="utf-8") as f:
        json.dump(products, f, separators=(",", ":"), ensure_ascii=False)

    # ── Stats summary ──
    store_stats = conn.execute("""
        SELECT store,
               COUNT(*) as count,
               ROUND(AVG(price), 2) as avg_price,
               MIN(scraped_at) as first_scraped,
               MAX(scraped_at) as last_scraped
        FROM products
        WHERE price IS NOT NULL
        GROUP BY store
        ORDER BY count DESC
    """).fetchall()

    cat_stats = conn.execute("""
        SELECT category, COUNT(*) as count
        FROM products
        WHERE category IS NOT NULL
        GROUP BY category
        ORDER BY count DESC
    """).fetchall()

    cheapest = conn.execute("""
        SELECT category, store, ROUND(AVG(price), 2) as avg_price
        FROM products
        WHERE price IS NOT NULL AND category IS NOT NULL
        GROUP BY category, store
        ORDER BY category, avg_price
    """).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    on_sale = conn.execute("SELECT COUNT(*) FROM products WHERE on_sale = 1").fetchone()[0]

    stats = {
        "total": total,
        "on_sale": on_sale,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stores": [dict(r) for r in store_stats],
        "categories": [dict(r) for r in cat_stats],
        "cheapest_by_cat": [dict(r) for r in cheapest],
    }

    with open(os.path.join(DOCS_DATA, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, separators=(",", ":"), ensure_ascii=False)

    conn.close()

    print(f"Exported {len(products)} products to docs/data/products.json")
    print(f"Exported stats to docs/data/stats.json")
    print(f"Total size: {os.path.getsize(os.path.join(DOCS_DATA, 'products.json')) / 1024:.0f} KB")


if __name__ == "__main__":
    export()
