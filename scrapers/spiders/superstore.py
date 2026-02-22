"""
Real Canadian Superstore Scraper — Loblaw Iceberg platform.
Uses proven data-testid selectors found via page inspection.
"""

import re
import scrapy
from scrapers.items import GroceryItem, GroceryItemLoader

CATEGORIES = [
    {"name": "Produce", "url": "https://www.realcanadiansuperstore.ca/food/fruits-vegetables/c/28000"},
    {"name": "Dairy & Eggs", "url": "https://www.realcanadiansuperstore.ca/food/dairy-eggs/c/28001"},
    {"name": "Meat & Seafood", "url": "https://www.realcanadiansuperstore.ca/food/meat-seafood/c/28002"},
    {"name": "Bakery", "url": "https://www.realcanadiansuperstore.ca/food/bakery/c/28003"},
    {"name": "Pantry", "url": "https://www.realcanadiansuperstore.ca/food/pantry/c/28004"},
    {"name": "Frozen", "url": "https://www.realcanadiansuperstore.ca/food/frozen/c/28005"},
    {"name": "Snacks & Candy", "url": "https://www.realcanadiansuperstore.ca/food/snacks-chips/c/28006"},
    {"name": "Beverages", "url": "https://www.realcanadiansuperstore.ca/food/drinks/c/28007"},
]

JS_EXTRACT = """
() => {
    const results = [];
    const titles = document.querySelectorAll('[data-testid="product-title"]');
    titles.forEach(titleEl => {
        let parent = titleEl.parentElement;
        let depth = 0;
        while (parent && depth < 10) {
            const hasPrice = parent.querySelector('[data-testid="price-product-tile"]');
            if (hasPrice) {
                const brand = parent.querySelector('[data-testid="product-brand"]');
                const size = parent.querySelector('[data-testid="product-package-size"]');
                const regPrice = parent.querySelector('[data-testid="regular-price"]');
                const salePrice = parent.querySelector('[data-testid="sale-price"]');
                const wasPrice = parent.querySelector('[data-testid="was-price"]');
                const img = parent.querySelector('img');
                const link = parent.tagName === 'A' ? parent :
                             parent.closest('a') || parent.querySelector('a');

                let priceText = '';
                if (salePrice) {
                    priceText = salePrice.textContent.replace(/sale/i, '').trim();
                } else if (regPrice) {
                    priceText = regPrice.textContent.replace(/about/i, '').trim();
                }

                results.push({
                    name: titleEl.textContent.trim(),
                    brand: brand ? brand.textContent.trim() : '',
                    price: priceText,
                    wasPrice: wasPrice ? wasPrice.textContent.replace(/was/i, '').trim() : '',
                    size: size ? size.textContent.trim() : '',
                    image: img ? (img.src || img.dataset.src || '') : '',
                    url: link ? link.href : '',
                });
                break;
            }
            parent = parent.parentElement;
            depth++;
        }
    });
    return results;
}
"""


class SuperstoreSpider(scrapy.Spider):
    name = "superstore"
    store_name = "superstore"

    custom_settings = {
        "DOWNLOAD_DELAY": 5,
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
            await page.wait_for_timeout(6000)

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(1500)

            products = await page.evaluate(JS_EXTRACT)
            self.logger.info(f"[Superstore] {category}: found {len(products)} products")

            seen = set()
            for p in products:
                item = self._build_item(p, category)
                if item and item.get("product_name") not in seen:
                    seen.add(item.get("product_name"))
                    yield item

        except Exception as e:
            self.logger.error(f"[Superstore] Error in {category}: {e}")
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
        loader.add_value("store", "Real Canadian Superstore")
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
            url = f"https://www.realcanadiansuperstore.ca{url}"
        loader.add_value("url", url)
        loader.add_value("in_stock", True)
        return loader.load_item()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()
        self.logger.error(f"[Superstore] Error: {failure}")
