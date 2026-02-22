"""
Calgary Grocery Scraper — Main Runner
Scrape grocery prices from all major Calgary stores.

Usage:
    python run_scraper.py --all              # Scrape all stores
    python run_scraper.py --store walmart    # Scrape one store
    python run_scraper.py --store superstore nofrills  # Multiple stores
    python run_scraper.py --clear            # Clear old DB and scrape fresh
"""

import argparse
import os
import sys
import subprocess
import sqlite3
from datetime import datetime


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "grocery_prices.db")

STORES = ["walmart", "superstore", "saveonfoods", "nofrills", "safeway"]


def clear_database():
    """Remove old scrape data."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("🗑️  Cleared old database.")
    # Also remove CSVs
    for f in os.listdir(DATA_DIR) if os.path.exists(DATA_DIR) else []:
        if f.endswith(".csv"):
            os.remove(os.path.join(DATA_DIR, f))
    print("✅ Ready for fresh scrape.")


def run_spider(spider_name):
    """Run a single Scrapy spider."""
    print(f"\n{'='*60}")
    print(f"🕷️  Scraping {spider_name.upper()}...")
    print(f"{'='*60}")
    start = datetime.now()

    result = subprocess.run(
        [sys.executable, "-m", "scrapy", "crawl", spider_name],
        cwd=os.path.dirname(__file__),
    )

    elapsed = (datetime.now() - start).total_seconds()
    if result.returncode == 0:
        print(f"✅ {spider_name} completed in {elapsed:.1f}s")
    else:
        print(f"⚠️  {spider_name} finished with errors (code {result.returncode}) in {elapsed:.1f}s")

    return result.returncode


def show_summary():
    """Print a summary of scraped data."""
    if not os.path.exists(DB_PATH):
        print("\n📭 No data scraped yet.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    total = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"📊 SCRAPING SUMMARY")
    print(f"{'='*60}")
    print(f"Total products: {total}")

    stores = cursor.execute("""
        SELECT store, COUNT(*) as count, ROUND(AVG(price), 2) as avg
        FROM products WHERE price IS NOT NULL
        GROUP BY store ORDER BY count DESC
    """).fetchall()

    for store, count, avg in stores:
        print(f"  {store}: {count} products (avg ${avg})")

    on_sale = cursor.execute("SELECT COUNT(*) FROM products WHERE on_sale = 1").fetchone()[0]
    print(f"\nItems on sale: {on_sale}")

    conn.close()
    print(f"\n🌐 Start the web UI:  python web/app.py")
    print(f"   Then open: http://127.0.0.1:5000")


def main():
    parser = argparse.ArgumentParser(description="Calgary Grocery Price Scraper")
    parser.add_argument("--all", action="store_true", help="Scrape all stores")
    parser.add_argument("--store", nargs="+", choices=STORES, help="Scrape specific store(s)")
    parser.add_argument("--clear", action="store_true", help="Clear old data before scraping")
    parser.add_argument("--list", action="store_true", help="List available stores")
    args = parser.parse_args()

    if args.list:
        print("Available stores:")
        for s in STORES:
            print(f"  - {s}")
        return

    if args.clear:
        clear_database()

    stores_to_scrape = []
    if args.all:
        stores_to_scrape = STORES
    elif args.store:
        stores_to_scrape = args.store
    else:
        parser.print_help()
        print("\n💡 Quick start: python run_scraper.py --all")
        return

    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🛒 Calgary Grocery Price Scraper")
    print(f"📍 Location: Calgary, AB")
    print(f"🏪 Stores to scrape: {', '.join(stores_to_scrape)}")
    print(f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for store in stores_to_scrape:
        run_spider(store)

    show_summary()


if __name__ == "__main__":
    main()
