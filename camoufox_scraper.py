"""
Camoufox Stealth Scraper (Workshop Challenge 7)
Uses Camoufox — an undetectable Firefox fork — to bypass:
- CDP protocol detection (Walmart)
- Akamai Bot Manager (Costco)
- WebDriver flag checks
- Browser fingerprint consistency checks

Scrapes Walmart.ca and Costco.ca which block regular Playwright.
Stores results in the same SQLite DB used by the Flask web UI.

Usage:
    python camoufox_scraper.py --store walmart          # Walmart only
    python camoufox_scraper.py --store costco            # Costco only
    python camoufox_scraper.py --all                     # Both stores
    python camoufox_scraper.py --store walmart --query "milk"  # Single search
    python camoufox_scraper.py --all --proxy socks5://user:pass@host:port
"""

import argparse
import re
import sqlite3
import os
import sys
import time
import random
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "grocery_prices.db")

# Search terms per category
SEARCH_TERMS = {
    "Produce": ["apples", "bananas", "potatoes", "lettuce", "tomatoes", "oranges", "carrots", "onions"],
    "Dairy & Eggs": ["milk", "eggs", "cheese", "yogurt", "butter", "cream"],
    "Meat & Seafood": ["chicken breast", "ground beef", "salmon", "pork chops", "bacon", "sausage"],
    "Bakery & Bread": ["bread", "bagels", "tortillas", "muffins"],
    "Pantry": ["rice", "pasta", "cereal", "canned soup", "flour", "cooking oil", "peanut butter"],
    "Frozen": ["frozen pizza", "ice cream", "frozen vegetables", "frozen fries"],
    "Snacks": ["chips", "crackers", "cookies", "chocolate", "nuts"],
    "Beverages": ["orange juice", "coffee", "water", "pop", "tea"],
}

# Store-specific JS extraction functions
WALMART_JS = """
() => {
    const results = [];
    const bodyText = document.body.textContent || '';
    if (bodyText.includes('not robots') || bodyText.includes('Access Denied') ||
        document.title.includes('Verify')) {
        return {blocked: true, results: []};
    }

    // Walmart product tiles
    const cards = document.querySelectorAll(
        '[data-testid="product-tile"], [data-item-id], ' +
        '[data-automation-id="product"], div[class*="product"][class*="tile"]'
    );
    const productLinks = cards.length > 0 ? [] :
        document.querySelectorAll('a[href*="/ip/"], a[link-identifier]');
    const allCards = cards.length > 0 ? cards : productLinks;

    allCards.forEach(card => {
        try {
            let container = card.tagName === 'A' ?
                (card.closest('[data-item-id]') || card.parentElement?.parentElement || card) : card;

            const nameEl = container.querySelector(
                'span[data-automation-id="product-title"], span[data-automation-id="name"], ' +
                '[data-testid="product-title"], h2, h3'
            ) || card.querySelector('span');

            const priceEl = container.querySelector(
                '[data-automation-id="product-price"], [itemprop="price"], ' +
                'div[class*="price"] span:first-child, [data-testid*="price"]'
            );

            const name = nameEl ? nameEl.textContent.trim() : '';
            if (name.length > 2) {
                const item = {name};
                if (priceEl) {
                    item.price = priceEl.textContent.trim()
                        .replace(/current price/i, '').replace(/was /i, '').trim();
                }
                const brandEl = container.querySelector('[data-automation-id="product-brand"]');
                if (brandEl) item.brand = brandEl.textContent.trim();
                const sizeEl = container.querySelector('span[data-automation-id="product-description"]');
                if (sizeEl) item.size = sizeEl.textContent.trim();
                const img = container.querySelector('img');
                if (img) item.image = img.src || img.dataset.src || '';
                const link = container.querySelector('a[href*="/ip/"]') || container.querySelector('a');
                if (link) item.url = link.href;
                const wasEl = container.querySelector('[data-automation-id="was-price"], s, del');
                if (wasEl) item.wasPrice = wasEl.textContent.trim();
                results.push(item);
            }
        } catch(e) {}
    });

    // JSON-LD fallback
    if (results.length === 0) {
        document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
            try {
                const d = JSON.parse(s.textContent);
                const items = d['@type'] === 'ItemList' ? d.itemListElement : [];
                items.forEach(e => {
                    const p = e.item || e;
                    if (p.name) results.push({
                        name: p.name,
                        price: p.offers ? (p.offers.price || '') : '',
                        url: p.url || '', image: p.image || '',
                        brand: p.brand ? (p.brand.name || p.brand) : '',
                    });
                });
            } catch(e) {}
        });
    }
    return {blocked: false, results};
}
"""

COSTCO_JS = """
() => {
    const results = [];
    const bodyText = document.body.textContent || '';
    if (bodyText.includes('Access Denied') || bodyText.includes('Reference #') ||
        bodyText.includes('enable JavaScript and cookies')) {
        return {blocked: true, results: []};
    }

    // Try multiple selector strategies
    const selectors = [
        // data-testid-based (newer Costco)
        '[data-testid^="ProductTile"]',
        // Class-based
        'div.product-tile', '.product', '[class*="ProductCard"]',
        // Search result tiles
        '#search-results .product', '.product-list .product',
        // Gallery-style
        '.product-tile-set .product', '.tile-list .product',
        // MUI-based
        '.MuiBox-root a[href*="/product/"]',
    ];

    let cards = [];
    for (const sel of selectors) {
        cards = document.querySelectorAll(sel);
        if (cards.length > 0) break;
    }

    cards.forEach(card => {
        try {
            const container = card.closest('.product') || card;
            const nameEl = container.querySelector(
                'a[data-testid="Link"] span, span[class*="description"], ' +
                'p[class*="description"], a.product-title, .product-name, h3, h2, a span'
            );
            const priceEl = container.querySelector(
                '[data-testid^="Text_Price"], div[class*="price"], ' +
                'span[class*="price"], .price, .MuiTypography-t5'
            );
            const name = nameEl ? nameEl.textContent.trim() : '';
            if (name.length > 3) {
                const item = {name};
                if (priceEl) item.price = priceEl.textContent.trim();
                const img = container.querySelector('img');
                if (img) item.image = img.src || '';
                const link = container.querySelector('a[href*="/product/"]') ||
                    container.querySelector('a[href*=".product."]') ||
                    container.querySelector('a');
                if (link) item.url = link.href;
                results.push(item);
            }
        } catch(e) {}
    });

    // JSON-LD fallback
    if (results.length === 0) {
        document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
            try {
                const d = JSON.parse(s.textContent);
                const items = d['@type'] === 'ItemList' ? d.itemListElement :
                    d['@type'] === 'Product' ? [d] : [];
                items.forEach(e => {
                    const p = e.item || e;
                    if (p.name) results.push({
                        name: p.name,
                        price: p.offers ? (p.offers.price || '') : '',
                        url: p.url || '', image: p.image || '',
                    });
                });
            } catch(e) {}
        });
    }
    return {blocked: false, results};
}
"""

STORE_CONFIG = {
    "walmart": {
        "search_url": "https://www.walmart.ca/search?q={query}&c=10019",
        "js_extract": WALMART_JS,
        "display_name": "Walmart",
    },
    "costco": {
        "search_url": "https://www.costco.ca/s?keyword={query}&lang=en-CA",
        "js_extract": COSTCO_JS,
        "display_name": "Costco",
    },
}


def ensure_db():
    """Create DB and table if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT, brand TEXT, price REAL, regular_price REAL,
            unit_price REAL, unit TEXT, size TEXT, category TEXT, store TEXT,
            store_location TEXT, url TEXT, image_url TEXT, in_stock BOOLEAN,
            on_sale BOOLEAN, scraped_at TEXT,
            UNIQUE(product_name, store, size)
        )
    """)
    conn.commit()
    conn.close()


def save_products(products, store_name, category):
    """Save products to SQLite with UPSERT."""
    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for p in products:
        name = p.get("name", "").strip()
        if not name or len(name) < 3:
            continue
        # Skip non-product text
        if any(x in name.lower() for x in ["sponsored", "add to cart", "see more", "showing"]):
            continue

        price_str = p.get("price", "")
        match = re.search(r'(\d+\.?\d*)', str(price_str).replace(",", ""))
        price = round(float(match.group(1)), 2) if match else None

        was_str = p.get("wasPrice", "")
        was_match = re.search(r'(\d+\.?\d*)', str(was_str).replace(",", "")) if was_str else None
        regular_price = round(float(was_match.group(1)), 2) if was_match else None

        on_sale = bool(regular_price and price and price < regular_price)

        try:
            conn.execute("""
                INSERT INTO products (
                    product_name, brand, price, regular_price, unit_price,
                    unit, size, category, store, store_location,
                    url, image_url, in_stock, on_sale, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_name, store, size) DO UPDATE SET
                    price = excluded.price,
                    regular_price = excluded.regular_price,
                    on_sale = excluded.on_sale,
                    scraped_at = excluded.scraped_at
            """, (
                name,
                p.get("brand", ""),
                price,
                regular_price,
                None,  # unit_price
                "each",
                p.get("size", ""),
                category,
                store_name,
                "Calgary, AB",
                p.get("url", ""),
                p.get("image", ""),
                True,
                on_sale,
                datetime.now().isoformat(),
            ))
            saved += 1
        except Exception as e:
            pass
    conn.commit()
    conn.close()
    return saved


def _scrape_walmart(query=None, categories=None, proxy=None):
    """
    Scrape Walmart.ca using curl_cffi (browser TLS fingerprint impersonation).
    Fetches the search HTML page, then extracts products from the embedded
    __NEXT_DATA__ JSON.  Supports pagination (up to MAX_PAGES per search).
    """
    from curl_cffi import requests as cffi_requests
    from urllib.parse import quote

    MAX_PAGES = 3  # Walmart returns ~40 items/page

    session = cffi_requests.Session(impersonate="chrome131")
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    # Build search list
    if query:
        search_list = [("Search", query)]
    else:
        search_list = []
        cats = categories or list(SEARCH_TERMS.keys())
        for cat in cats:
            for term in SEARCH_TERMS.get(cat, []):
                search_list.append((cat, term))

    print(f"\n{'='*60}")
    print(f"  Walmart — {len(search_list)} searches via curl_cffi")
    print(f"{'='*60}")

    total_saved = 0
    total_found = 0

    # Visit homepage first to acquire Akamai cookies
    print("  Warming up: visiting Walmart.ca homepage...")
    try:
        r = session.get("https://www.walmart.ca/", timeout=20)
        if r.status_code == 200:
            print("  Homepage OK — cookies acquired")
        else:
            print(f"  Homepage returned {r.status_code} — continuing anyway")
    except Exception as e:
        print(f"  Homepage failed: {e} — continuing anyway")
    time.sleep(random.uniform(2, 4))

    for i, (category, term) in enumerate(search_list):
        print(f"  [{i+1}/{len(search_list)}] Searching: '{term}' ({category})")
        term_found = 0

        for page_num in range(1, MAX_PAGES + 1):
            try:
                url = f"https://www.walmart.ca/search?q={quote(term)}&c=10019"
                if page_num > 1:
                    url += f"&page={page_num}"

                r = session.get(url, timeout=20)
                if r.status_code != 200:
                    print(f"    Page {page_num}: HTTP {r.status_code}")
                    break

                # Extract __NEXT_DATA__ JSON
                nd_match = re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                    r.text, re.DOTALL
                )
                if not nd_match:
                    # Check if we got a CAPTCHA / blocked page
                    if "Verify Your Identity" in r.text or "blocked" in r.text:
                        print(f"    BLOCKED by PerimeterX")
                    else:
                        print(f"    No __NEXT_DATA__ found")
                    break

                import json as json_mod
                nd = json_mod.loads(nd_match.group(1))
                search_result = (
                    nd.get("props", {})
                      .get("pageProps", {})
                      .get("initialData", {})
                      .get("searchResult", {})
                )

                stacks = search_result.get("itemStacks", [])
                if not stacks:
                    break

                items = stacks[0].get("items", [])
                if not items:
                    break

                products = []
                for item in items:
                    name = item.get("name", "")
                    if not name or item.get("__typename") == "AdPlaceholder":
                        continue

                    pi = item.get("priceInfo", {})
                    price_str = pi.get("linePrice", "") or pi.get("itemPrice", "")
                    # Strip "$" and whitespace for clean numeric value
                    price_clean = price_str.replace("$", "").strip() if price_str else ""

                    was_raw = pi.get("wasPrice", "")
                    was_clean = was_raw.replace("$", "").strip() if was_raw else ""

                    img = item.get("imageInfo", {}).get("thumbnailUrl", "")
                    canon = item.get("canonicalUrl", "")
                    full_url = f"https://www.walmart.ca{canon}" if canon else ""

                    products.append({
                        "name": name,
                        "price": price_clean,
                        "brand": item.get("brand", ""),
                        "size": pi.get("unitPrice", ""),   # e.g. "25¢/100ml"
                        "url": full_url,
                        "image": img,
                        "wasPrice": was_clean,
                    })

                total_found += len(products)
                term_found += len(products)

                if products:
                    saved = save_products(products, "Walmart", category)
                    total_saved += saved

                # Check if there are more pages
                max_page = (
                    search_result.get("paginationV2", {}).get("maxPage", 1)
                )
                if page_num >= max_page:
                    break

                time.sleep(random.uniform(2, 4))

            except Exception as e:
                print(f"    Page {page_num} error: {e}")
                break

        if term_found:
            print(f"    Found {term_found} products")
        else:
            print(f"    No products found")

        # Delay between searches to avoid rate limiting
        time.sleep(random.uniform(3, 7))

    print(f"\n  Walmart TOTAL: found {total_found}, saved {total_saved}")
    return total_saved


def scrape_store(store_key, query=None, categories=None, proxy=None):
    """
    Scrape a store with Camoufox stealth browser.
    If query is provided, search for that single term.
    Otherwise, iterate through all category search terms.
    """
    # For Walmart, try the API approach first (much more reliable)
    if store_key == "walmart":
        return _scrape_walmart(query, categories, proxy)

    try:
        from camoufox.sync_api import Camoufox
        from camoufox.pkgman import camoufox_path, launch_path
    except ImportError:
        print("Camoufox not installed. Install with: pip install camoufox[geoip]")
        return 0

    config = STORE_CONFIG[store_key]
    total_saved = 0
    total_found = 0

    # Build list of (category, term) pairs to scrape
    if query:
        search_list = [("Search", query)]
    else:
        search_list = []
        cats = categories or list(SEARCH_TERMS.keys())
        for cat in cats:
            for term in SEARCH_TERMS.get(cat, []):
                search_list.append((cat, term))

    print(f"\n{'='*60}")
    print(f"  {config['display_name']} — {len(search_list)} searches with Camoufox")
    print(f"{'='*60}")

    # Windows Store Python UWP sandbox fix: Playwright's Node.js driver can't see
    # the sandboxed path, so we copy Camoufox to a real filesystem location.
    real_camoufox_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "camoufox_real"
    )
    real_exe_path = os.path.join(
        real_camoufox_dir, "camoufox", "Cache", "camoufox.exe"
    )
    sandboxed_dir = camoufox_path()  # UWP-virtualized path
    if not os.path.isfile(real_exe_path) or (
        os.path.getmtime(launch_path()) > os.path.getmtime(real_exe_path)
    ):
        import shutil
        print("  Copying Camoufox to non-sandboxed path...")
        if os.path.exists(real_camoufox_dir):
            shutil.rmtree(real_camoufox_dir)
        shutil.copytree(
            os.path.dirname(sandboxed_dir),  # parent of Cache dir
            real_camoufox_dir,
        )
        print(f"  Copied to {real_camoufox_dir}")

    # Point to real filesystem exe if it exists, else use default
    exe_override = real_exe_path if os.path.isfile(real_exe_path) else None

    def _scroll_and_extract(page, js_extract):
        """Scroll the page like a human, then extract products."""
        time.sleep(random.uniform(3, 6))
        for scroll_i in range(4):
            page.evaluate(f"window.scrollTo(0, {(scroll_i + 1) * 600})")
            time.sleep(random.uniform(0.8, 2.0))
        return page.evaluate(js_extract)

    # ── Costco strategy: one browser, homepage warmup, batch searches.
    #    Costco needs Akamai cookies from the homepage but tolerates reuse.
    # Costco tolerates multiple searches per session after homepage warmup
    COSTCO_BATCH = 6  # searches per browser session before rotating
    for batch_start in range(0, len(search_list), COSTCO_BATCH):
        batch = search_list[batch_start:batch_start + COSTCO_BATCH]
        try:
            with Camoufox(headless=True, geoip=True,
                          executable_path=exe_override) as browser:
                page = browser.new_page()

                # Homepage warmup for Akamai cookies
                print("  Warming up: visiting Costco.ca homepage...")
                page.goto("https://www.costco.ca",
                          wait_until="domcontentloaded", timeout=60000)
                time.sleep(random.uniform(6, 10))
                hp_text = page.evaluate(
                    "document.body.textContent.substring(0, 300)"
                )
                if "Access Denied" in hp_text:
                    print("  Homepage blocked — rotating session")
                    time.sleep(random.uniform(15, 25))
                    continue
                print("  Homepage OK — cookies acquired")

                for j, (category, term) in enumerate(batch):
                    idx = batch_start + j + 1
                    url = config["search_url"].format(query=term)
                    print(f"  [{idx}/{len(search_list)}] Searching: '{term}' ({category})")
                    try:
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=45000)
                        result = _scroll_and_extract(
                            page, config["js_extract"]
                        )

                        if result.get("blocked"):
                            print(f"    BLOCKED — rotating session")
                            break

                        products = result.get("results", [])
                        total_found += len(products)
                        if products:
                            saved = save_products(
                                products, config["display_name"], category
                            )
                            total_saved += saved
                            print(f"    Found {len(products)}, saved {saved}")
                        else:
                            print(f"    No products found")

                        time.sleep(random.uniform(5, 10))

                    except Exception as e:
                        print(f"    Error: {e}")
                        time.sleep(random.uniform(5, 10))

                page.close()

        except Exception as e:
            print(f"  Session error: {e}")

        # Delay between browser sessions
        time.sleep(random.uniform(10, 20))

    print(f"\n  {config['display_name']} TOTAL: found {total_found}, saved {total_saved}")
    return total_saved


def main():
    parser = argparse.ArgumentParser(
        description="Stealth grocery scraper using Camoufox for bot-protected sites"
    )
    parser.add_argument("--store", choices=list(STORE_CONFIG.keys()),
                        help="Store to scrape (walmart or costco)")
    parser.add_argument("--all", action="store_true",
                        help="Scrape all stealth-required stores")
    parser.add_argument("--query", help="Single search term (e.g. 'milk')")
    parser.add_argument("--categories", nargs="+",
                        help="Categories to scrape (e.g. 'Produce' 'Dairy & Eggs')")
    parser.add_argument("--proxy",
                        help="HTTP/SOCKS5 proxy URL (e.g. http://user:pass@host:port)")
    args = parser.parse_args()

    if not args.store and not args.all:
        parser.print_help()
        print("\nExamples:")
        print("  python camoufox_scraper.py --store walmart")
        print("  python camoufox_scraper.py --all")
        print("  python camoufox_scraper.py --store walmart --query milk")
        print("  python camoufox_scraper.py --store walmart --proxy http://user:pass@host:port")
        sys.exit(1)

    ensure_db()

    stores = list(STORE_CONFIG.keys()) if args.all else [args.store]
    grand_total = 0

    for store in stores:
        saved = scrape_store(store, query=args.query, categories=args.categories,
                             proxy=args.proxy)
        grand_total += saved

    print(f"\n{'='*60}")
    print(f"  DONE — {grand_total} total products saved to DB")
    print(f"  View results: python web/app.py -> http://127.0.0.1:5000")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
