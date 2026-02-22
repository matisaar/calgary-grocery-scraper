"""
Save-On-Foods Scraper — uses search endpoint which works with Playwright.
data-testid selectors: ProductCardWrapper, ProductCardAQABrand, ProductNameTestId,
productCardPricing-div-testId.
"""

import re
import scrapy
from scrapers.items import GroceryItem, GroceryItemLoader

# Search terms cover all major grocery categories
SEARCH_TERMS = [
    ("Dairy & Eggs", ["milk", "eggs", "cheese", "yogurt", "butter", "cream"]),
    ("Produce", ["apples", "bananas", "potatoes", "lettuce", "tomatoes", "oranges"]),
    ("Meat & Seafood", ["chicken", "beef", "salmon", "pork", "bacon", "sausage"]),
    ("Bakery", ["bread", "bagels", "muffins"]),
    ("Pantry", ["rice", "pasta", "cereal", "soup", "canned beans", "flour"]),
    ("Frozen", ["frozen pizza", "ice cream", "frozen vegetables"]),
    ("Beverages", ["orange juice", "coffee", "tea", "water", "pop"]),
    ("Snacks", ["chips", "crackers", "cookies", "chocolate"]),
]

JS_EXTRACT = """
() => {
    const results = [];
    const cards = document.querySelectorAll('article[data-testid^="ProductCardWrapper-"]');
    cards.forEach(card => {
        try {
            // Brand from ProductCardAQABrand
            const brandEl = card.querySelector('[data-testid="ProductCardAQABrand"]');
            // Product name from *-ProductNameTestId
            const nameEl = card.querySelector('[data-testid$="-ProductNameTestId"]');
            // Price from productCardPricing-div-testId
            const priceEl = card.querySelector('[data-testid="productCardPricing-div-testId"]');
            // Image
            const imgEl = card.querySelector('[data-testid$="-testId"] img, img');
            // Link  
            const linkEl = card.querySelector('a');

            // Fallback: get name from the aria paragraph
            const ariaP = card.querySelector('.AriaProductTitleParagraph--1yc7f4f, p[aria-hidden="true"]');
            
            let name = '';
            if (nameEl) {
                name = nameEl.textContent.trim();
            } else if (ariaP) {
                // aria text format: "Brand - Name, Size, $Price"
                name = ariaP.textContent.trim();
                // Extract just the product name part
                const parts = name.split(',');
                if (parts.length > 1) {
                    name = parts[0].trim(); // "Brand - Name"
                }
            }

            if (name.length > 2) {
                const brand = brandEl ? brandEl.textContent.trim() : '';
                let priceText = priceEl ? priceEl.textContent.trim() : '';
                const imgSrc = imgEl ? (imgEl.src || imgEl.dataset.src || '') : '';
                const url = linkEl ? linkEl.href : '';

                // Extract size from aria paragraph if available
                let size = '';
                if (ariaP) {
                    const full = ariaP.textContent.trim();
                    const parts = full.split(',');
                    if (parts.length >= 2) {
                        // Second part is usually the size
                        size = parts[parts.length - 2].trim();
                        // Remove price from size if accidentally included
                        if (size.startsWith('$')) size = '';
                    }
                }

                results.push({
                    name: name,
                    brand: brand,
                    price: priceText,
                    size: size,
                    image: imgSrc,
                    url: url,
                });
            }
        } catch(e) {}
    });
    return results;
}
"""


class SaveOnFoodsSpider(scrapy.Spider):
    name = "saveonfoods"
    store_name = "saveonfoods"

    custom_settings = {
        "DOWNLOAD_DELAY": 6,
        "CONCURRENT_REQUESTS": 1,
    }

    def start_requests(self):
        for category, terms in SEARCH_TERMS:
            for term in terms:
                url = f"https://www.saveonfoods.com/sm/pickup/rsid/8820/results?q={term}"
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
            # Wait for products to render
            await page.wait_for_timeout(8000)

            # Scroll to load more
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(2000)

            products = await page.evaluate(JS_EXTRACT)
            self.logger.info(
                f"[Save-On-Foods] '{search_term}' ({category}): found {len(products)} products"
            )

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

        except Exception as e:
            self.logger.error(f"[Save-On-Foods] Error for '{search_term}': {e}")
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
        loader.add_value("store", "Save-On-Foods")
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
            url = f"https://www.saveonfoods.com{url}"
        loader.add_value("url", url)
        loader.add_value("in_stock", True)
        return loader.load_item()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"[Save-On-Foods] Error: {failure}")
