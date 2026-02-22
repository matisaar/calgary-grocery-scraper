"""
Scrapy Items for Calgary Grocery Price Comparison
Defines the data structure for grocery products across all stores.
"""

import scrapy
from scrapy.loader import ItemLoader
from itemloaders.processors import TakeFirst, MapCompose, Join
import re


def clean_price(value):
    """Extract numeric price from strings like '$4.99', '4.99/lb', '$ 3 . 49'."""
    if not value:
        return None
    # Remove whitespace inside price
    cleaned = re.sub(r'\s+', '', str(value))
    # Extract the numeric price
    match = re.search(r'(\d+\.?\d*)', cleaned)
    if match:
        return float(match.group(1))
    return None


def clean_text(value):
    """Strip whitespace and normalize text."""
    if not value:
        return ""
    return " ".join(str(value).split()).strip()


def clean_unit(value):
    """Normalize unit strings like '/lb', 'per kg', 'each'."""
    if not value:
        return "each"
    v = str(value).lower().strip()
    if "kg" in v:
        return "per kg"
    elif "lb" in v:
        return "per lb"
    elif "100" in v and "g" in v:
        return "per 100g"
    elif "l" in v or "ml" in v:
        return "per L"
    return "each"


class GroceryItem(scrapy.Item):
    """A single grocery product listing."""
    product_name = scrapy.Field()
    brand = scrapy.Field()
    price = scrapy.Field()
    regular_price = scrapy.Field()   # before sale
    unit_price = scrapy.Field()      # price per standard unit
    unit = scrapy.Field()            # 'each', 'per kg', 'per lb', 'per 100g'
    size = scrapy.Field()            # e.g. '500g', '1L', '12 pack'
    category = scrapy.Field()        # e.g. 'Produce', 'Dairy', 'Meat'
    store = scrapy.Field()           # 'walmart', 'superstore', etc.
    store_location = scrapy.Field()  # 'Calgary, AB'
    url = scrapy.Field()
    image_url = scrapy.Field()
    in_stock = scrapy.Field()
    on_sale = scrapy.Field()
    scraped_at = scrapy.Field()


class GroceryItemLoader(ItemLoader):
    """Loader with default processors for grocery items."""
    default_item_class = GroceryItem
    default_output_processor = TakeFirst()

    product_name_in = MapCompose(clean_text)
    brand_in = MapCompose(clean_text)
    price_in = MapCompose(clean_price)
    regular_price_in = MapCompose(clean_price)
    unit_price_in = MapCompose(clean_price)
    unit_in = MapCompose(clean_unit)
    size_in = MapCompose(clean_text)
    category_in = MapCompose(clean_text)
    store_in = MapCompose(clean_text)
    url_in = MapCompose(clean_text)
    image_url_in = MapCompose(clean_text)
