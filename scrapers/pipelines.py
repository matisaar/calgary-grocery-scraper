"""
Scrapy Pipelines for Calgary Grocery Scraper
- CleanPricePipeline: normalizes prices
- DeduplicationPipeline: removes duplicate products
- SQLitePipeline: stores results in SQLite for the web UI
- CSVExportPipeline: exports per-store CSV files
"""

import csv
import hashlib
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class CleanPricePipeline:
    """Ensure prices are floats and flag sales."""

    def process_item(self, item, **kwargs):
        # Ensure price is float
        price = item.get("price")
        if price is not None:
            try:
                item["price"] = round(float(price), 2)
            except (ValueError, TypeError):
                item["price"] = None

        reg = item.get("regular_price")
        if reg is not None:
            try:
                item["regular_price"] = round(float(reg), 2)
            except (ValueError, TypeError):
                item["regular_price"] = None

        # Determine if on sale
        if item.get("price") and item.get("regular_price"):
            item["on_sale"] = item["price"] < item["regular_price"]
        elif item.get("on_sale") is None:
            item["on_sale"] = False

        # Default values
        item.setdefault("unit", "each")
        item.setdefault("in_stock", True)
        item.setdefault("store_location", "Calgary, AB")
        item["scraped_at"] = datetime.now().isoformat()

        return item


class DeduplicationPipeline:
    """Drop duplicate items based on store + product_name + size."""

    def __init__(self):
        self.seen = set()

    def process_item(self, item, **kwargs):
        key_str = f"{item.get('store', '')}|{item.get('product_name', '')}|{item.get('size', '')}"
        key = hashlib.md5(key_str.encode()).hexdigest()
        if key in self.seen:
            from scrapy.exceptions import DropItem
            raise DropItem(f"Duplicate: {item.get('product_name')}")
        self.seen.add(key)
        return item


class SQLitePipeline:
    """Store all products in a SQLite DB for the comparison web UI."""

    DB_PATH = os.path.join(DATA_DIR, "grocery_prices.db")

    def open_spider(self, **kwargs):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.conn = sqlite3.connect(self.DB_PATH)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT,
                brand TEXT,
                price REAL,
                regular_price REAL,
                unit_price REAL,
                unit TEXT,
                size TEXT,
                category TEXT,
                store TEXT,
                store_location TEXT,
                url TEXT,
                image_url TEXT,
                in_stock BOOLEAN,
                on_sale BOOLEAN,
                scraped_at TEXT,
                UNIQUE(product_name, store, size)
            )
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_product_name ON products(product_name)
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_store ON products(store)
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON products(category)
        """)
        self.conn.commit()

    def process_item(self, item, **kwargs):
        # UPSERT: update price if product already exists, else insert
        self.cursor.execute("""
            INSERT INTO products (
                product_name, brand, price, regular_price, unit_price,
                unit, size, category, store, store_location,
                url, image_url, in_stock, on_sale, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_name, store, size) DO UPDATE SET
                price = excluded.price,
                regular_price = excluded.regular_price,
                unit_price = excluded.unit_price,
                on_sale = excluded.on_sale,
                in_stock = excluded.in_stock,
                image_url = excluded.image_url,
                url = excluded.url,
                scraped_at = excluded.scraped_at
        """, (
            item.get("product_name"),
            item.get("brand"),
            item.get("price"),
            item.get("regular_price"),
            item.get("unit_price"),
            item.get("unit"),
            item.get("size"),
            item.get("category"),
            item.get("store"),
            item.get("store_location"),
            item.get("url"),
            item.get("image_url"),
            item.get("in_stock"),
            item.get("on_sale"),
            item.get("scraped_at"),
        ))
        self.conn.commit()
        return item

    def close_spider(self, **kwargs):
        self.conn.close()


class CSVExportPipeline:
    """Export per-store CSV files for easy inspection."""

    FIELDS = [
        "product_name", "brand", "price", "regular_price", "unit_price",
        "unit", "size", "category", "store", "store_location", "url",
        "image_url", "in_stock", "on_sale", "scraped_at",
    ]

    def open_spider(self, **kwargs):
        os.makedirs(DATA_DIR, exist_ok=True)
        spider = kwargs.get('spider')
        store = getattr(spider, 'store_name', spider.name) if spider else 'grocery'
        path = os.path.join(DATA_DIR, f"{store}_products.csv")
        self.file = open(path, "w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDS, extrasaction="ignore")
        self.writer.writeheader()

    def process_item(self, item, **kwargs):
        self.writer.writerow(dict(item))
        return item

    def close_spider(self, **kwargs):
        self.file.close()
