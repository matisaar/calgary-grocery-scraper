# Calgary Grocery Price Comparison Scraper
# Applies anti-detection techniques from Fabien's WebScraping Anti-Ban Workshop

BOT_NAME = "calgary_grocery_scraper"

SPIDER_MODULES = ["scrapers.spiders"]
NEWSPIDER_MODULE = "scrapers.spiders"

# ---------- Anti-Detection Settings (Workshop Challenge 2: Headers) ----------
# Rotate realistic User-Agents to avoid fingerprinting
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ---------- Respectful Crawling ----------
ROBOTSTXT_OBEY = False  # Grocery sites block scrapers in robots.txt
CONCURRENT_REQUESTS = 4
DOWNLOAD_DELAY = 2
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# ---------- Retry Settings ----------
RETRY_ENABLED = True
RETRY_TIMES = 5
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504]

# ---------- Download Handlers (Workshop Challenge 4: Playwright) ----------
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Playwright options — headless stealth mode
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--window-size=1920,1080",
    ],
}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 60000  # 60s

# ---------- Middlewares ----------
DOWNLOADER_MIDDLEWARES = {
    "scrapers.middlewares.anti_detection.AntiDetectionMiddleware": 400,
    "scrapers.middlewares.user_agent_rotator.UserAgentRotatorMiddleware": 410,
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
    "scrapers.middlewares.smart_retry.SmartRetryMiddleware": 550,
}

SPIDER_MIDDLEWARES = {}

# ---------- Pipelines ----------
ITEM_PIPELINES = {
    "scrapers.pipelines.CleanPricePipeline": 100,
    "scrapers.pipelines.DeduplicationPipeline": 200,
    "scrapers.pipelines.SQLitePipeline": 300,
    "scrapers.pipelines.CSVExportPipeline": 400,
}

# ---------- Feeds ----------
# We handle export ourselves via pipeline, but keep this as backup
# FEEDS = {
#     "data/results.csv": {"format": "csv", "overwrite": True},
# }

# ---------- Logging ----------
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# ---------- Cache (speeds up development) ----------
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = "httpcache"

# ---------- Scrapoxy Proxy Support (Workshop Challenge 3) ----------
# Uncomment and configure if you set up Scrapoxy
# PROXY = "http://localhost:8888"
# HTTPPROXY_AUTH_ENCODING = "utf-8"
# SCRAPOXY_USERNAME = "admin"
# SCRAPOXY_PASSWORD = "password"

# ---------- Calgary-specific ----------
CALGARY_POSTAL_CODE = "T2P"  # Downtown Calgary area code
CALGARY_STORE_LOCATION = "Calgary, AB"
