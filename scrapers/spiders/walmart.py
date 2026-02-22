"""
Walmart Canada Scraper — walmart.ca with aggressive bot evasion.
Uses a two-phase approach:
  1. First navigates to a benign page to get cookies/session
  2. Then browses categories + search with those cookies
Includes store-location pre-selection (Calgary Deerfoot) and
search-based fallback when category pages are blocked.
"""

import re
import scrapy
from scrapers.items import GroceryItem, GroceryItemLoader

# Browse-based category URLs
CATEGORIES = [
    {"name": "Produce", "url": "https://www.walmart.ca/browse/grocery/fruits-vegetables/10019-10784"},
    {"name": "Dairy & Eggs", "url": "https://www.walmart.ca/browse/grocery/dairy-eggs/10019-10785"},
    {"name": "Meat & Seafood", "url": "https://www.walmart.ca/browse/grocery/meat-seafood/10019-10786"},
    {"name": "Bakery & Bread", "url": "https://www.walmart.ca/browse/grocery/bread-bakery/10019-10790"},
    {"name": "Pantry", "url": "https://www.walmart.ca/browse/grocery/pantry/10019-10787"},
    {"name": "Frozen", "url": "https://www.walmart.ca/browse/grocery/frozen/10019-10788"},
    {"name": "Snacks & Candy", "url": "https://www.walmart.ca/browse/grocery/snacks-candy/10019-10791"},
    {"name": "Beverages", "url": "https://www.walmart.ca/browse/grocery/beverages/10019-10789"},
]

# Search-based fallback — used if browse pages get blocked
SEARCH_TERMS = [
    ("Produce", ["apples", "bananas", "potatoes", "lettuce", "tomatoes", "oranges", "carrots"]),
    ("Dairy & Eggs", ["milk", "eggs", "cheese", "yogurt", "butter", "cream"]),
    ("Meat & Seafood", ["chicken breast", "ground beef", "salmon", "pork chops", "bacon"]),
    ("Bakery & Bread", ["bread", "bagels", "tortillas"]),
    ("Pantry", ["rice", "pasta", "cereal", "canned soup", "flour", "cooking oil"]),
    ("Frozen", ["frozen pizza", "ice cream", "frozen vegetables", "frozen fries"]),
    ("Snacks & Candy", ["chips", "crackers", "cookies", "chocolate"]),
    ("Beverages", ["orange juice", "coffee", "water bottles", "pop"]),
]

JS_EXTRACT = """
() => {
    const results = [];

    // Check if we got blocked
    const bodyText = document.body.textContent || '';
    if (document.title.includes('Verify') ||
        bodyText.includes('not robots') ||
        bodyText.includes('blocked') ||
        bodyText.includes('Access Denied')) {
        return {blocked: true, results: []};
    }

    // Walmart.ca uses data-automation-id extensively
    const cards = document.querySelectorAll(
        '[data-testid="product-tile"], ' +
        '[data-item-id], ' +
        '[data-automation-id="product"], ' +
        'div[class*="product"][class*="tile"], ' +
        'section[class*="product"]'
    );

    // Also try generic link-based product detection
    const productLinks = cards.length > 0 ? [] :
        document.querySelectorAll('a[href*="/ip/"], a[link-identifier]');

    const allCards = cards.length > 0 ? cards : productLinks;

    allCards.forEach(card => {
        try {
            // Walk up to find the product container if we started from a link
            let container = card;
            if (card.tagName === 'A') {
                container = card.closest('[data-item-id]') ||
                           card.closest('[data-testid]') ||
                           card.parentElement?.parentElement || card;
            }

            const nameEl = container.querySelector(
                'span[data-automation-id="product-title"], ' +
                'span[data-automation-id="name"], ' +
                '[data-testid="product-title"], ' +
                'h2, h3'
            ) || card.querySelector('span');

            const priceEl = container.querySelector(
                '[data-automation-id="product-price"], ' +
                '[itemprop="price"], ' +
                'div[class*="price"] span:first-child, ' +
                '[data-testid*="price"]'
            );

            const brandEl = container.querySelector(
                '[data-automation-id="product-brand"], ' +
                'span[class*="brand"]'
            );

            const sizeEl = container.querySelector(
                'span[class*="description"], span[class*="size"], ' +
                'span[data-automation-id="product-description"]'
            );

            const name = nameEl ? nameEl.textContent.trim() : '';
            if (name.length > 2) {
                const item = {name: name};

                if (priceEl) {
                    // Walmart prices sometimes have ¢ symbol or "current price" prefix
                    let priceText = priceEl.textContent.trim()
                        .replace(/current price/i, '')
                        .replace(/was /i, '')
                        .trim();
                    item.price = priceText;
                }

                if (brandEl) item.brand = brandEl.textContent.trim();
                if (sizeEl) item.size = sizeEl.textContent.trim();

                const img = container.querySelector('img[data-testid="productTileImage"], img');
                if (img) item.image = img.src || img.dataset.src || '';

                const link = container.tagName === 'A' ? container :
                    container.querySelector('a[href*="/ip/"]') ||
                    container.querySelector('a[link-identifier]') ||
                    container.querySelector('a');
                if (link) item.url = link.href;

                // Check for sale price patterns
                const wasEl = container.querySelector(
                    '[data-automation-id="was-price"], ' +
                    'span[class*="was"], s, del'
                );
                if (wasEl) item.wasPrice = wasEl.textContent.trim();

                results.push(item);
            }
        } catch(e) {}
    });

    // Fallback: JSON-LD structured data
    if (results.length === 0) {
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        scripts.forEach(script => {
            try {
                const data = JSON.parse(script.textContent);
                const items = data['@type'] === 'ItemList' ? data.itemListElement :
                    Array.isArray(data) ? data.filter(d => d['@type'] === 'Product') : [];
                items.forEach(entry => {
                    const prod = entry.item || entry;
                    if (prod.name) {
                        results.push({
                            name: prod.name,
                            price: prod.offers ? (prod.offers.price || prod.offers.lowPrice || '') : '',
                            image: prod.image || '',
                            url: prod.url || '',
                            brand: prod.brand ? (prod.brand.name || prod.brand) : '',
                        });
                    }
                });
            } catch(e) {}
        });
    }

    return {blocked: false, results, cardCount: allCards.length};
}
"""


class WalmartSpider(scrapy.Spider):
    name = "walmart"
    store_name = "walmart"
    browse_blocked = False  # Track if browse pages are blocked

    custom_settings = {
        "DOWNLOAD_DELAY": 8,
        "CONCURRENT_REQUESTS": 1,
    }

    def _pw_context(self):
        return {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-CA",
            "timezone_id": "America/Edmonton",
            # Pre-set Walmart's Calgary store location cookies
            "storage_state": {
                "cookies": [
                    {"name": "deliveryCatchment", "value": "3000",
                     "domain": ".walmart.ca", "path": "/"},
                    {"name": "walmart.nearestPostalCode", "value": "T2G 9Z0",
                     "domain": ".walmart.ca", "path": "/"},
                    {"name": "walmart.nearestLatLng", "value": "51.0447,-114.0719",
                     "domain": ".walmart.ca", "path": "/"},
                    {"name": "defaultNearestStoreId", "value": "1015",
                     "domain": ".walmart.ca", "path": "/"},
                ],
                "origins": [],
            },
        }

    def start_requests(self):
        # Phase 1: warm up with browse categories
        for cat in CATEGORIES:
            yield scrapy.Request(
                url=cat["url"],
                callback=self.parse_category,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_context_kwargs": self._pw_context(),
                    "category": cat["name"],
                },
                errback=self.errback_close_page,
            )

    async def parse_category(self, response):
        page = response.meta.get("playwright_page")
        category = response.meta.get("category", "")

        try:
            # Wait for page to fully load
            await page.wait_for_timeout(6000)

            # Dismiss any modals/popups (store selector, cookies, etc.)
            for selector in ['button[aria-label="Close"]', 'button:has-text("Close")',
                           'button:has-text("Accept")', '[data-automation-id="modal-close"]']:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await page.wait_for_timeout(1000)
                except:
                    pass

            # Scroll to trigger lazy-loading
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(1500)

            result = await page.evaluate(JS_EXTRACT)

            if result.get("blocked"):
                self.logger.warning(
                    f"[Walmart] {category}: BLOCKED — switching to search mode"
                )
                self.browse_blocked = True
                # Yield search-based requests as fallback
                for cat_name, terms in SEARCH_TERMS:
                    if cat_name == category:
                        for term in terms:
                            yield scrapy.Request(
                                url=f"https://www.walmart.ca/search?q={term}&c=10019",
                                callback=self.parse_search,
                                meta={
                                    "playwright": True,
                                    "playwright_include_page": True,
                                    "playwright_context_kwargs": self._pw_context(),
                                    "category": cat_name,
                                    "search_term": term,
                                },
                                errback=self.errback_close_page,
                            )
                return

            products = result.get("results", [])
            self.logger.info(
                f"[Walmart] {category}: found {len(products)} products "
                f"(cards: {result.get('cardCount', '?')})"
            )

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

            # If browse worked but yielded few results, also try search
            if len(products) < 5 and not self.browse_blocked:
                for cat_name, terms in SEARCH_TERMS:
                    if cat_name == category:
                        for term in terms[:3]:  # Limit to first 3 terms
                            yield scrapy.Request(
                                url=f"https://www.walmart.ca/search?q={term}&c=10019",
                                callback=self.parse_search,
                                meta={
                                    "playwright": True,
                                    "playwright_include_page": True,
                                    "playwright_context_kwargs": self._pw_context(),
                                    "category": cat_name,
                                    "search_term": term,
                                },
                                errback=self.errback_close_page,
                            )

        except Exception as e:
            self.logger.error(f"[Walmart] Error in {category}: {e}")
        finally:
            if page:
                await page.close()

    async def parse_search(self, response):
        page = response.meta.get("playwright_page")
        category = response.meta.get("category", "")
        search_term = response.meta.get("search_term", "")

        try:
            await page.wait_for_timeout(6000)

            # Dismiss modals
            try:
                close_btn = page.locator('button[aria-label="Close"]').first
                if await close_btn.is_visible(timeout=1000):
                    await close_btn.click()
                    await page.wait_for_timeout(500)
            except:
                pass

            # Scroll
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(1500)

            result = await page.evaluate(JS_EXTRACT)

            if result.get("blocked"):
                self.logger.warning(f"[Walmart] Search '{search_term}': BLOCKED")
                return

            products = result.get("results", [])
            self.logger.info(
                f"[Walmart] Search '{search_term}' ({category}): found {len(products)} products"
            )

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

        except Exception as e:
            self.logger.error(f"[Walmart] Error searching '{search_term}': {e}")
        finally:
            if page:
                await page.close()

    def _build_item(self, data, category):
        name = data.get("name", "")
        if not name or len(name) < 3:
            return None
        # Skip non-product text
        if any(skip in name.lower() for skip in [
            "sponsored", "add to cart", "view details", "see more",
            "pickup", "delivery", "rollback"
        ]):
            return None

        loader = GroceryItemLoader(item=GroceryItem())
        loader.add_value("product_name", name)
        loader.add_value("brand", data.get("brand", ""))
        loader.add_value("category", category)
        loader.add_value("store", "Walmart")
        loader.add_value("store_location", "Calgary, AB")

        price_str = data.get("price", "")
        if price_str:
            match = re.search(r'(\d+\.?\d*)', str(price_str).replace(",", ""))
            if match:
                loader.add_value("price", float(match.group(1)))

        was_str = data.get("wasPrice", "")
        if was_str:
            match = re.search(r'(\d+\.?\d*)', str(was_str).replace(",", ""))
            if match:
                loader.add_value("regular_price", float(match.group(1)))
                loader.add_value("on_sale", True)

        loader.add_value("size", data.get("size", ""))
        loader.add_value("image_url", data.get("image", ""))

        url = data.get("url", "")
        if url and not url.startswith("http"):
            url = f"https://www.walmart.ca{url}"
        loader.add_value("url", url)
        loader.add_value("in_stock", True)
        return loader.load_item()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"[Walmart] Request error: {failure}")
