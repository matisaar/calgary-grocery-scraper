"""
Calgary Grocery Price Comparison — Web UI
Flask app that reads from the SQLite database and displays
price comparisons across all scraped stores.
"""

import os
import sqlite3
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "grocery_prices.db")


def get_db():
    """Get a SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db():
    """Create the DB and table if they don't exist (for first run)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            brand TEXT,
            price REAL,
            regular_price REAL,
            unit_price REAL,
            unit TEXT,
            size TEXT,
            category TEXT,
            store TEXT,
            store_location TEXT,
            url TEXT,
            image_url TEXT,
            in_stock BOOLEAN,
            on_sale BOOLEAN,
            scraped_at TEXT
        )
    """)
    conn.commit()
    conn.close()


@app.route("/")
def index():
    """Home page with search and category browsing."""
    ensure_db()
    db = get_db()

    # Get all categories and stores for filters
    categories = [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category"
    ).fetchall()]

    stores = [r[0] for r in db.execute(
        "SELECT DISTINCT store FROM products WHERE store IS NOT NULL ORDER BY store"
    ).fetchall()]

    # Get total counts
    total = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    on_sale = db.execute("SELECT COUNT(*) FROM products WHERE on_sale = 1").fetchone()[0]

    # Get cheapest finds today (lowest price items)
    deals = db.execute("""
        SELECT product_name, brand, price, regular_price, store, category, url, image_url, size,
               CASE WHEN regular_price IS NOT NULL AND regular_price > price
                    THEN ROUND((1 - price/regular_price) * 100, 0)
                    ELSE 0 END as discount_pct
        FROM products
        WHERE price IS NOT NULL AND on_sale = 1
        ORDER BY discount_pct DESC
        LIMIT 12
    """).fetchall()

    db.close()
    return render_template(
        "index.html",
        categories=categories,
        stores=stores,
        total=total,
        on_sale=on_sale,
        deals=deals,
    )


@app.route("/search")
def search():
    """Search products across all stores and compare prices."""
    ensure_db()
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    store = request.args.get("store", "")
    sort = request.args.get("sort", "price_asc")

    if not query and not category:
        return render_template("search.html", products=[], query="", grouped={})

    db = get_db()

    sql = "SELECT * FROM products WHERE 1=1"
    params = []

    if query:
        sql += " AND (product_name LIKE ? OR brand LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])

    if category:
        sql += " AND category = ?"
        params.append(category)

    if store:
        sql += " AND store = ?"
        params.append(store)

    sql += " AND price IS NOT NULL"

    # Sorting
    sort_map = {
        "price_asc": "price ASC",
        "price_desc": "price DESC",
        "name": "product_name ASC",
        "store": "store ASC, price ASC",
        "discount": "CASE WHEN regular_price IS NOT NULL THEN (regular_price - price) ELSE 0 END DESC",
    }
    sql += f" ORDER BY {sort_map.get(sort, 'price ASC')}"
    sql += " LIMIT 200"

    products = db.execute(sql, params).fetchall()

    # Group by similar product name for comparison view
    grouped = {}
    for p in products:
        # Normalize name for grouping (lowercase, strip brand/size)
        key = p["product_name"].lower().strip() if p["product_name"] else "unknown"
        # Simplify grouping key — take first 4 words
        words = key.split()[:4]
        group_key = " ".join(words)
        if group_key not in grouped:
            grouped[group_key] = []
        grouped[group_key].append(dict(p))

    # Get filter options
    categories = [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category"
    ).fetchall()]
    stores = [r[0] for r in db.execute(
        "SELECT DISTINCT store FROM products WHERE store IS NOT NULL ORDER BY store"
    ).fetchall()]

    db.close()
    return render_template(
        "search.html",
        products=[dict(p) for p in products],
        query=query,
        grouped=grouped,
        categories=categories,
        stores=stores,
        selected_category=category,
        selected_store=store,
        selected_sort=sort,
    )


@app.route("/category/<category_name>")
def category(category_name):
    """Browse a full category with price comparison across stores."""
    ensure_db()
    db = get_db()

    products = db.execute("""
        SELECT *, 
               CASE WHEN regular_price IS NOT NULL AND regular_price > price
                    THEN ROUND((1 - price/regular_price) * 100, 0)
                    ELSE 0 END as discount_pct
        FROM products 
        WHERE category = ? AND price IS NOT NULL
        ORDER BY product_name, price ASC
    """, [category_name]).fetchall()

    stores = [r[0] for r in db.execute(
        "SELECT DISTINCT store FROM products WHERE category = ? ORDER BY store",
        [category_name]
    ).fetchall()]

    db.close()
    return render_template(
        "category.html",
        category=category_name,
        products=[dict(p) for p in products],
        stores=stores,
    )


@app.route("/api/search")
def api_search():
    """JSON API endpoint for AJAX search."""
    ensure_db()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    db = get_db()
    products = db.execute("""
        SELECT product_name, brand, price, regular_price, unit_price, unit,
               size, category, store, url, image_url, on_sale
        FROM products
        WHERE (product_name LIKE ? OR brand LIKE ?) AND price IS NOT NULL
        ORDER BY price ASC
        LIMIT 50
    """, [f"%{query}%", f"%{query}%"]).fetchall()

    db.close()
    return jsonify([dict(p) for p in products])


@app.route("/api/compare")
def api_compare():
    """Compare a specific product across all stores."""
    ensure_db()
    product_name = request.args.get("product", "").strip()
    if not product_name:
        return jsonify([])

    db = get_db()
    products = db.execute("""
        SELECT product_name, brand, price, regular_price, unit_price, unit,
               size, store, url, image_url, on_sale
        FROM products
        WHERE product_name LIKE ? AND price IS NOT NULL
        ORDER BY price ASC
    """, [f"%{product_name}%"]).fetchall()

    db.close()
    return jsonify([dict(p) for p in products])


@app.route("/stats")
def stats():
    """Show scraping statistics and store price analysis."""
    ensure_db()
    db = get_db()

    # Products per store
    store_counts = db.execute("""
        SELECT store, COUNT(*) as count, 
               ROUND(AVG(price), 2) as avg_price,
               MIN(scraped_at) as first_scraped,
               MAX(scraped_at) as last_scraped
        FROM products
        WHERE price IS NOT NULL
        GROUP BY store
        ORDER BY count DESC
    """).fetchall()

    # Products per category
    cat_counts = db.execute("""
        SELECT category, COUNT(*) as count
        FROM products
        WHERE category IS NOT NULL
        GROUP BY category
        ORDER BY count DESC
    """).fetchall()

    # Cheapest store per category
    cheapest_by_cat = db.execute("""
        SELECT category, store, ROUND(AVG(price), 2) as avg_price
        FROM products
        WHERE price IS NOT NULL AND category IS NOT NULL
        GROUP BY category, store
        ORDER BY category, avg_price
    """).fetchall()

    db.close()
    return render_template(
        "stats.html",
        store_counts=[dict(r) for r in store_counts],
        cat_counts=[dict(r) for r in cat_counts],
        cheapest_by_cat=[dict(r) for r in cheapest_by_cat],
    )


if __name__ == "__main__":
    ensure_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
