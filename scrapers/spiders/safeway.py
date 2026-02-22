"""
Safeway Canada Scraper — uses Voilà online grocery platform.
Safeway.ca redirects to voila.ca for online shopping.
Uses JSON-LD structured data and visible product cards.
"""

import re
import json
import scrapy
from scrapers.items import GroceryItem, GroceryItemLoader

SEARCH_TERMS = [
    ("Dairy & Eggs", ["milk", "eggs", "cheese", "yogurt", "butter"]),
    ("Produce", ["apples", "bananas", "potatoes", "lettuce", "tomatoes"]),
    ("Meat & Seafood", ["chicken", "beef", "salmon", "pork", "bacon"]),
    ("Bakery", ["bread", "bagels", "muffins"]),
    ("Pantry", ["rice", "pasta", "cereal", "soup", "flour"]),
    ("Frozen", ["frozen pizza", "ice cream", "frozen vegetables"]),
    ("Beverages", ["orange juice", "coffee", "tea"]),
    ("Snacks", ["chips", "crackers", "cookies"]),
]

# Extract products from Voilà's rendered page + JSON-LD
JS_EXTRACT = """
() => {
    const results = [];

    // Method 1: JSON-LD structured data (schema.org/ItemList)
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    scripts.forEach(script => {
        try {
            const data = JSON.parse(script.textContent);
            if (data['@type'] === 'ItemList' && data.itemListElement) {
                data.itemListElement.forEach(item => {
                    if (item['@type'] === 'ListItem' && item.item) {
                        const prod = item.item;
                        results.push({
                            name: prod.name || '',
                            price: prod.offers ? (prod.offers.price || '') : '',
                            image: prod.image || '',
                            url: prod.url || '',
                            brand: prod.brand ? (prod.brand.name || prod.brand) : '',
                            size: prod.description || '',
                            source: 'jsonld',
                        });
                    }
                });
            }
        } catch(e) {}
    });

    // Method 2: Visible product cards
    if (results.length === 0) {
        const cards = document.querySelectorAll(
            '[class*="product-card"], [data-test*="product"], ' +
            '[class*="ProductCard"], article[class*="product"]'
        );
        cards.forEach(card => {
            try {
                const nameEl = card.querySelector('h2, h3, [class*="name"], [class*="title"]');
                const priceEl = card.querySelector('[class*="price"], [class*="Price"]');
                if (nameEl && nameEl.textContent.trim().length > 2) {
                    results.push({
                        name: nameEl.textContent.trim(),
                        price: priceEl ? priceEl.textContent.trim() : '',
                        image: '',
                        url: '',
                        brand: '',
                        size: '',
                        source: 'dom',
                    });
                }
            } catch(e) {}
        });
    }

    return results;
}
"""


class SafewaySpider(scrapy.Spider):
    name = "safeway"
    store_name = "safeway"

    custom_settings = {
        "DOWNLOAD_DELAY": 5,
        "CONCURRENT_REQUESTS": 1,
    }

    def start_requests(self):
        for category, terms in SEARCH_TERMS:
            for term in terms:
                url = f"https://voila.ca/search?q={term}&store=safeway"
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_search,
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
                        "category": category,
                        "search_term": term,
                    },
                    errback=self.errback_close_page,
                )

    async def parse_search(self, response):
        page = response.meta.get("playwright_page")
        category = response.meta.get("category", "")
        search_term = response.meta.get("search_term", "")

        try:
            await page.wait_for_timeout(8000)

            # Scroll to load more products
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(2000)

            products = await page.evaluate(JS_EXTRACT)
            self.logger.info(
                f"[Safeway/Voilà] '{search_term}' ({category}): found {len(products)} products"
            )

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

        except Exception as e:
            self.logger.error(f"[Safeway] Error for '{search_term}': {e}")
        finally:
            if page:
                await page.close()

    def _build_item(self, data, category):
        name = data.get("name", "")
        if not name or len(name) < 3:
            return None

        loader = GroceryItemLoader(item=GroceryItem())
        loader.add_value("product_name", name)
        loader.add_value("brand", data.get("brand", ""))
        loader.add_value("category", category)
        loader.add_value("store", "Safeway")
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
            url = f"https://voila.ca{url}"
        loader.add_value("url", url)
        loader.add_value("in_stock", True)
        return loader.load_item()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"[Safeway] Error: {failure}")
