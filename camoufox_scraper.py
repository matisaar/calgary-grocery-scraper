"""
Camoufox Stealth Scraper (Workshop Challenge 7)
An alternative scraper using Camoufox instead of Playwright
for sites with aggressive bot detection.

Camoufox is an undetectable Firefox fork that bypasses:
- CDP protocol detection
- WebDriver flag checks
- Browser fingerprint consistency checks

Use this when regular Playwright gets blocked.

Usage:
    python camoufox_scraper.py "milk" --store walmart
    python camoufox_scraper.py "chicken breast" --store safeway
"""

import argparse
import json
import sqlite3
import os
import sys
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "grocery_prices.db")

STORE_URLS = {
    "walmart": "https://www.walmart.ca/search?q={query}&c=10019&storeId=1015",
    "superstore": "https://www.realcanadiansuperstore.ca/search?search-bar={query}",
    "saveonfoods": "https://www.saveonfoods.com/sm/pickup/rsid/8820/search?searchTerm={query}",
    "nofrills": "https://www.nofrills.ca/search?search-bar={query}",
    "safeway": "https://www.safeway.ca/search?search-bar={query}",
}


def scrape_with_camoufox(query, store="walmart"):
    """
    Use Camoufox for stealth scraping when Playwright is detected.
    Falls back to regular Playwright if Camoufox isn't installed.
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        print("⚠️  Camoufox not installed. Install with: pip install camoufox[geoip]")
        print("    Falling back to regular Playwright...")
        return scrape_with_playwright(query, store)

    url = STORE_URLS.get(store, STORE_URLS["walmart"]).format(query=query)
    print(f"🦊 Scraping {store} with Camoufox: {url}")

    products = []
    with Camoufox(headless=True, geoip=True) as browser:
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)

        # Scroll to load more products
        for _ in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        # Extract product data via JS evaluation
        raw_products = page.evaluate("""
            () => {
                const products = [];
                // Generic selectors that work across most grocery sites
                const cards = document.querySelectorAll(
                    '[data-testid="product-card"], [data-testid="product-tile"], ' +
                    '.product-card, .product-tile, .ProductCard, ' +
                    '[class*="ProductCard"], [class*="product-tile"]'
                );
                cards.forEach(card => {
                    const nameEl = card.querySelector(
                        '[data-testid="product-title"], .product-name, .product-title, h3, h2'
                    );
                    const priceEl = card.querySelector(
                        '[data-testid="product-price"], .price, [class*="Price"], [class*="price"]'
                    );
                    const imgEl = card.querySelector('img');
                    const linkEl = card.querySelector('a');
                    
                    if (nameEl && priceEl) {
                        products.push({
                            name: nameEl.textContent.trim(),
                            price: priceEl.textContent.trim(),
                            image: imgEl ? imgEl.src : null,
                            url: linkEl ? linkEl.href : null,
                        });
                    }
                });
                return products;
            }
        """)

        products = raw_products
        page.close()

    return products


def scrape_with_playwright(query, store="walmart"):
    """Fallback: regular Playwright scraping."""
    from playwright.sync_api import sync_playwright

    url = STORE_URLS.get(store, STORE_URLS["walmart"]).format(query=query)
    print(f"🎭 Scraping {store} with Playwright: {url}")

    products = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-CA",
            timezone_id="America/Edmonton",  # Calgary timezone (Workshop Challenge 5)
        )
        page = context.new_page()

        # Stealth: mask webdriver flag (Workshop Challenge 7)
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            delete navigator.__proto__.webdriver;
        """)

        page.goto(url, wait_until="networkidle", timeout=60000)

        for _ in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        raw_products = page.evaluate("""
            () => {
                const products = [];
                const cards = document.querySelectorAll(
                    '[data-testid="product-card"], [data-testid="product-tile"], ' +
                    '.product-card, .product-tile, .ProductCard, ' +
                    '[class*="ProductCard"], [class*="product-tile"]'
                );
                cards.forEach(card => {
                    const nameEl = card.querySelector(
                        '[data-testid="product-title"], .product-name, .product-title, h3, h2'
                    );
                    const priceEl = card.querySelector(
                        '[data-testid="product-price"], .price, [class*="Price"], [class*="price"]'
                    );
                    const imgEl = card.querySelector('img');
                    const linkEl = card.querySelector('a');
                    
                    if (nameEl && priceEl) {
                        products.push({
                            name: nameEl.textContent.trim(),
                            price: priceEl.textContent.trim(),
                            image: imgEl ? imgEl.src : null,
                            url: linkEl ? linkEl.href : null,
                        });
                    }
                });
                return products;
            }
        """)

        products = raw_products
        browser.close()

    return products


def save_results(products, store, query):
    """Save results to SQLite."""
    import re

    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT, brand TEXT, price REAL, regular_price REAL,
            unit_price REAL, unit TEXT, size TEXT, category TEXT, store TEXT,
            store_location TEXT, url TEXT, image_url TEXT, in_stock BOOLEAN,
            on_sale BOOLEAN, scraped_at TEXT
        )
    """)

    count = 0
    for p in products:
        price_str = p.get("price", "")
        match = re.search(r'(\d+\.?\d*)', str(price_str).replace(",", ""))
        price = float(match.group(1)) if match else None

        if price:
            conn.execute("""
                INSERT INTO products (product_name, price, store, store_location,
                                      url, image_url, category, in_stock, on_sale, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p.get("name", ""),
                price,
                store.title(),
                "Calgary, AB",
                p.get("url", ""),
                p.get("image", ""),
                query,
                True,
                False,
                datetime.now().isoformat(),
            ))
            count += 1

    conn.commit()
    conn.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="Stealth grocery scraper using Camoufox")
    parser.add_argument("query", help="Product to search for (e.g. 'milk', 'bread')")
    parser.add_argument("--store", default="walmart", choices=list(STORE_URLS.keys()))
    parser.add_argument("--all-stores", action="store_true", help="Search all stores")
    args = parser.parse_args()

    stores = list(STORE_URLS.keys()) if args.all_stores else [args.store]

    for store in stores:
        try:
            products = scrape_with_camoufox(args.query, store)
            if products:
                saved = save_results(products, store, args.query)
                print(f"✅ {store}: Found {len(products)} products, saved {saved}")
            else:
                print(f"⚠️  {store}: No products found")
        except Exception as e:
            print(f"❌ {store}: Error — {e}")

    print(f"\n🌐 View results: python web/app.py → http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
