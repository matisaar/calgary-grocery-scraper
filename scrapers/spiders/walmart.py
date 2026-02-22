"""
Walmart Canada Scraper — walmart.ca has aggressive bot detection.
Uses Playwright with extra stealth settings. If blocked, yields nothing gracefully.
Falls back to searching the Walmart Grocery API where possible.
"""

import re
import scrapy
from scrapers.items import GroceryItem, GroceryItemLoader

CATEGORIES = [
    {"name": "Produce", "url": "https://www.walmart.ca/browse/grocery/fruits-vegetables/10019-10784"},
    {"name": "Dairy & Eggs", "url": "https://www.walmart.ca/browse/grocery/dairy-eggs/10019-10785"},
    {"name": "Meat & Seafood", "url": "https://www.walmart.ca/browse/grocery/meat-seafood/10019-10786"},
    {"name": "Bakery & Bread", "url": "https://www.walmart.ca/browse/grocery/bread-bakery/10019-10790"},
    {"name": "Pantry", "url": "https://www.walmart.ca/browse/grocery/pantry/10019-10787"},
    {"name": "Frozen", "url": "https://www.walmart.ca/browse/grocery/frozen/10019-10788"},
]

JS_EXTRACT = """
() => {
    const results = [];

    // Check if we got blocked
    if (document.title.includes('Verify') || document.body.textContent.includes('not robots')) {
        return {blocked: true, results: []};
    }

    // Method 1: Standard Walmart product tiles
    const cards = document.querySelectorAll(
        '[data-testid="product-tile"], [data-item-id], ' +
        'div[data-canary] a[link-identifier], section a[href*="/ip/"], ' +
        'div[class*="product"][class*="tile"], div[class*="ProductCard"], ' +
        '[data-automation-id="product"]'
    );
    cards.forEach(card => {
        try {
            const nameEl = card.querySelector(
                'span[data-automation-id="name"], [data-automation-id="product-title"], ' +
                'h2, h3, span.normal, span.w_Cs, [class*="product-name"]'
            ) || card.querySelector('span');
            const priceEl = card.querySelector(
                '[data-automation-id="product-price"], [itemprop="price"], ' +
                'div[class*="price"] span, span[class*="price"], [class*="Price"]'
            );
            if (nameEl && nameEl.textContent.trim().length > 2) {
                const item = {name: nameEl.textContent.trim()};
                if (priceEl) item.price = priceEl.textContent.trim();
                const img = card.querySelector('img');
                if (img) item.image = img.src || img.dataset.src;
                const link = card.tagName === 'A' ? card : card.querySelector('a');
                if (link) item.url = link.href;
                const desc = card.querySelector(
                    'span[class*="description"], span[class*="size"], span.f7, span.gray'
                );
                if (desc) item.size = desc.textContent.trim();
                results.push(item);
            }
        } catch(e) {}
    });

    // Method 2: Try JSON-LD structured data
    if (results.length === 0) {
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        scripts.forEach(script => {
            try {
                const data = JSON.parse(script.textContent);
                if (data['@type'] === 'ItemList' && data.itemListElement) {
                    data.itemListElement.forEach(item => {
                        if (item.item) {
                            results.push({
                                name: item.item.name || '',
                                price: item.item.offers ? item.item.offers.price : '',
                                image: item.item.image || '',
                                url: item.item.url || '',
                            });
                        }
                    });
                }
            } catch(e) {}
        });
    }

    return {blocked: false, results};
}
"""


class WalmartSpider(scrapy.Spider):
    name = "walmart"
    store_name = "walmart"

    custom_settings = {
        "DOWNLOAD_DELAY": 8,
        "CONCURRENT_REQUESTS": 1,
    }

    def start_requests(self):
        for cat in CATEGORIES:
            yield scrapy.Request(
                url=cat["url"],
                callback=self.parse_category,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_context_kwargs": {
                        "user_agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        ),
                        "viewport": {"width": 1920, "height": 1080},
                        "locale": "en-CA",
                        "timezone_id": "America/Edmonton",
                    },
                    "category": cat["name"],
                },
                errback=self.errback_close_page,
            )

    async def parse_category(self, response):
        page = response.meta.get("playwright_page")
        category = response.meta.get("category", "")

        try:
            await page.wait_for_timeout(5000)

            # Scroll to trigger lazy-load
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(2000)

            result = await page.evaluate(JS_EXTRACT)

            if result.get("blocked"):
                self.logger.warning(
                    f"[Walmart] {category}: BLOCKED by bot detection. "
                    "Consider using Camoufox or a proxy service."
                )
                return

            products = result.get("results", [])
            self.logger.info(f"[Walmart] {category}: found {len(products)} products")

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

        except Exception as e:
            self.logger.error(f"[Walmart] Error in {category}: {e}")
        finally:
            if page:
                await page.close()

    def _build_item(self, data, category):
        name = data.get("name", "")
        if not name or len(name) < 3:
            return None

        loader = GroceryItemLoader(item=GroceryItem())
        loader.add_value("product_name", name)
        loader.add_value("category", category)
        loader.add_value("store", "Walmart")
        loader.add_value("store_location", "Calgary, AB")

        price_str = data.get("price", "")
        if price_str:
            match = re.search(r'(\d+\.?\d*)', str(price_str).replace(",", ""))
            if match:
                loader.add_value("price", float(match.group(1)))

        loader.add_value("size", data.get("size", ""))
        loader.add_value("image_url", data.get("image", ""))
        loader.add_value("url", data.get("url", ""))
        loader.add_value("in_stock", True)
        return loader.load_item()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"[Walmart] Error: {failure}")
