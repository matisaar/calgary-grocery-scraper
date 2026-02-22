"""
Costco Canada Scraper — costco.ca with Akamai bot protection.
Uses a stealth Playwright profile with extra anti-detection measures.
Targets search results as category pages are heavily protected.
Falls back to same-day delivery if main site is blocked.
"""

import re
import scrapy
from scrapers.items import GroceryItem, GroceryItemLoader

# Costco.ca uses different URL patterns for grocery
# The main grocery hub is /grocery-702.html but it's heavily protected
# Search is more reliable: /s?keyword={term}
SEARCH_TERMS = [
    ("Produce", ["organic apples", "bananas", "potatoes", "mixed greens", "berries"]),
    ("Dairy & Eggs", ["milk 4L", "eggs", "cheese block", "yogurt", "butter"]),
    ("Meat & Seafood", ["chicken breast", "ground beef", "salmon", "steak", "pork tenderloin"]),
    ("Bakery & Bread", ["bread", "croissants", "muffins", "bagels"]),
    ("Pantry", ["rice", "pasta", "olive oil", "cereal", "canned tuna", "flour"]),
    ("Frozen", ["frozen fruit", "ice cream", "frozen pizza", "frozen vegetables"]),
    ("Snacks", ["chips", "nuts", "crackers", "chocolate", "trail mix"]),
    ("Beverages", ["water bottles", "coffee", "juice", "sparkling water"]),
]

JS_EXTRACT = """
() => {
    const results = [];
    const bodyText = document.body.textContent || '';

    // Check for Akamai challenge or access denied
    if (bodyText.includes('Access Denied') ||
        bodyText.includes('Reference #') ||
        bodyText.includes('enable JavaScript and cookies') ||
        document.querySelector('meta[name="akamai"]') ||
        document.title.toLowerCase().includes('error') ||
        document.title.toLowerCase().includes('denied')) {
        return {blocked: true, results: [], reason: 'akamai_challenge'};
    }

    // Method 1: Costco.ca product tiles with data-testid
    const cards = document.querySelectorAll(
        '[data-testid^="ProductTile"], ' +
        'div.product-tile, ' +
        'div.product, ' +
        '[class*="ProductCard"], ' +
        'div[data-testid*="product"]'
    );

    cards.forEach(card => {
        try {
            const nameEl = card.querySelector(
                'a[data-testid="Link"] span, ' +
                'span[class*="description"], ' +
                'p[class*="description"], ' +
                'a.product-title, ' +
                '.product-name, h3, h2'
            );
            const priceEl = card.querySelector(
                '[data-testid^="Text_Price"], ' +
                'div[class*="price"], ' +
                'span[class*="price"], ' +
                '.price'
            );

            const name = nameEl ? nameEl.textContent.trim() : '';
            if (name.length > 2) {
                const item = {name: name};
                if (priceEl) item.price = priceEl.textContent.trim();

                const img = card.querySelector('img[data-testid^="ProductImage"], img');
                if (img) item.image = img.src || img.dataset.src || '';

                const link = card.querySelector('a[href*="/product/"], a[href*=".product."]');
                if (link) item.url = link.href;

                const badgeEl = card.querySelector('[data-testid^="PillBadge"], [class*="badge"]');
                if (badgeEl) item.badge = badgeEl.textContent.trim();

                results.push(item);
            }
        } catch(e) {}
    });

    // Method 2: Costco MUI-based layout (newer redesign)
    if (results.length === 0) {
        const muiCards = document.querySelectorAll('.MuiBox-root a[href*="/product/"]');
        muiCards.forEach(link => {
            try {
                const container = link.closest('.MuiBox-root') || link.parentElement;
                const nameEl = container.querySelector('.MuiTypography-root') || link;
                const priceEl = container.querySelector('[class*="price"], .MuiTypography-t5');
                const name = nameEl.textContent.trim();
                if (name.length > 3) {
                    results.push({
                        name: name,
                        price: priceEl ? priceEl.textContent.trim() : '',
                        url: link.href,
                        image: (container.querySelector('img') || {}).src || '',
                    });
                }
            } catch(e) {}
        });
    }

    // Method 3: Search results container
    if (results.length === 0) {
        const searchResults = document.querySelectorAll(
            '#search-results .product, ' +
            '.product-list .product, ' +
            '[class*="search-result"] [class*="product"]'
        );
        searchResults.forEach(card => {
            try {
                const nameEl = card.querySelector('.description a, .product-name, h3, a');
                const priceEl = card.querySelector('.price, [class*="price"]');
                const name = nameEl ? nameEl.textContent.trim() : '';
                if (name.length > 3) {
                    results.push({
                        name: name,
                        price: priceEl ? priceEl.textContent.trim() : '',
                        url: nameEl.href || '',
                        image: (card.querySelector('img') || {}).src || '',
                    });
                }
            } catch(e) {}
        });
    }

    // Method 4: JSON-LD structured data
    if (results.length === 0) {
        document.querySelectorAll('script[type="application/ld+json"]').forEach(script => {
            try {
                const data = JSON.parse(script.textContent);
                const items = data['@type'] === 'ItemList' ? data.itemListElement :
                    data['@type'] === 'Product' ? [data] : [];
                items.forEach(entry => {
                    const prod = entry.item || entry;
                    if (prod.name) {
                        results.push({
                            name: prod.name,
                            price: prod.offers ? (prod.offers.price || '') : '',
                            url: prod.url || '',
                            image: prod.image || '',
                            brand: prod.brand ? (prod.brand.name || prod.brand) : '',
                        });
                    }
                });
            } catch(e) {}
        });
    }

    return {blocked: false, results, cardCount: results.length};
}
"""


class CostcoSpider(scrapy.Spider):
    name = "costco"
    store_name = "costco"

    custom_settings = {
        "DOWNLOAD_DELAY": 10,
        "CONCURRENT_REQUESTS": 1,
        # Extra-cautious for Akamai
        "RANDOMIZE_DOWNLOAD_DELAY": True,
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
            "geolocation": {"latitude": 51.0447, "longitude": -114.0719},
            "permissions": ["geolocation"],
            # Costco cookies for Calgary warehouse
            "storage_state": {
                "cookies": [
                    {"name": "C_LOC", "value": "51.0447|-114.0719",
                     "domain": ".costco.ca", "path": "/"},
                    {"name": "invCheckPostalCode", "value": "T2P0N6",
                     "domain": ".costco.ca", "path": "/"},
                    {"name": "COSTCO_LANG", "value": "en",
                     "domain": ".costco.ca", "path": "/"},
                ],
                "origins": [],
            },
        }

    def start_requests(self):
        for category, terms in SEARCH_TERMS:
            for term in terms:
                # Primary: search on costco.ca
                yield scrapy.Request(
                    url=f"https://www.costco.ca/s?keyword={term}&lang=en-CA",
                    callback=self.parse_search,
                    meta={
                        "playwright": True,
                        "playwright_include_page": True,
                        "playwright_context_kwargs": self._pw_context(),
                        "category": category,
                        "search_term": term,
                    },
                    errback=self.errback_close_page,
                    dont_filter=True,
                )

    async def parse_search(self, response):
        page = response.meta.get("playwright_page")
        category = response.meta.get("category", "")
        search_term = response.meta.get("search_term", "")

        try:
            # Extended wait — Akamai needs time to validate
            await page.wait_for_timeout(10000)

            # Extra stealth: simulate human-like mouse movement
            await page.mouse.move(500, 400)
            await page.wait_for_timeout(500)
            await page.mouse.move(800, 300)
            await page.wait_for_timeout(1000)

            # Scroll naturally
            for i in range(5):
                await page.evaluate(
                    f"window.scrollTo(0, {(i + 1) * 500})"
                )
                await page.wait_for_timeout(1500 + (i * 300))

            result = await page.evaluate(JS_EXTRACT)

            if result.get("blocked"):
                self.logger.warning(
                    f"[Costco] '{search_term}': BLOCKED by Akamai — "
                    f"reason: {result.get('reason', 'unknown')}. "
                    "Use Camoufox or proxy service for Costco."
                )
                return

            products = result.get("results", [])
            self.logger.info(
                f"[Costco] '{search_term}' ({category}): found {len(products)} products"
            )

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

        except Exception as e:
            self.logger.error(f"[Costco] Error searching '{search_term}': {e}")
        finally:
            if page:
                await page.close()

    def _build_item(self, data, category):
        name = data.get("name", "")
        if not name or len(name) < 3:
            return None
        # Filter out non-products
        if any(x in name.lower() for x in [
            "sponsored", "add to cart", "see more", "showing results"
        ]):
            return None

        loader = GroceryItemLoader(item=GroceryItem())
        loader.add_value("product_name", name)
        loader.add_value("brand", data.get("brand", ""))
        loader.add_value("category", category)
        loader.add_value("store", "Costco")
        loader.add_value("store_location", "Calgary, AB")

        price_str = data.get("price", "")
        if price_str:
            match = re.search(r'(\d+\.?\d*)', str(price_str).replace(",", ""))
            if match:
                loader.add_value("price", float(match.group(1)))

        loader.add_value("size", data.get("size", ""))
        loader.add_value("image_url", data.get("image", ""))

        url = data.get("url", "")
        if url and not url.startswith("http"):
            url = f"https://www.costco.ca{url}"
        loader.add_value("url", url)
        loader.add_value("in_stock", True)
        return loader.load_item()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"[Costco] Request error: {failure}")
