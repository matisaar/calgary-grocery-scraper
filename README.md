# Calgary Grocery Price Comparison Scraper

A web scraping tool that compares grocery prices across major Calgary stores,
built using techniques from **Fabien's WebScraping Anti-Ban Workshop**.

## Stores Scraped

| Store | Method | Products | Notes |
|-------|--------|----------|-------|
| **Walmart** | `curl_cffi` (browser TLS impersonation) | ~3,600+ | Bypasses PerimeterX via __NEXT_DATA__ extraction |
| **Real Canadian Superstore** | Scrapy + Playwright | ~1,200+ | Loblaw PCX platform, pagination |
| **No Frills** | Scrapy + Playwright | ~700+ | Same Loblaw platform, pagination |
| **Costco** | Camoufox stealth browser | ~450+ | Akamai Bot Manager — homepage warmup trick |

## Anti-Detection Techniques Used

From the workshop:
- **Challenge 2**: Realistic HTTP headers (User-Agent, Sec-CH-UA, Referer)
- **Challenge 3**: Smart retry with exponential backoff (mimics rate limit bypass)
- **Challenge 4**: Playwright for JS-rendered sites (SPAs that need a browser)
- **Challenge 5**: Timezone/locale consistency (America/Edmonton for Calgary)
- **Challenge 7**: Camoufox stealth browser (optional, for aggressive bot detection)

Plus:
- User-Agent rotation across 7 modern browser UAs
- Per-store Referer headers
- Randomized Accept-Language variants
- Download delay + jitter to avoid rate limits

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```

### 2. Scrape all stores

```bash
# Loblaw stores (Superstore + No Frills) via Scrapy
python run_scraper.py --all

# Walmart + Costco via stealth scraper
python camoufox_scraper.py --all
```

Or scrape specific stores:

```bash
python run_scraper.py --store superstore
python camoufox_scraper.py --store walmart
python camoufox_scraper.py --store costco
python camoufox_scraper.py --store walmart --query "milk"
python camoufox_scraper.py --store walmart --proxy http://user:pass@host:port
```

### 3. View the comparison website

```bash
python web/app.py
```

Then open http://127.0.0.1:5000

## Stealth Scraper (Camoufox + curl_cffi)

For sites with aggressive bot detection:

```bash
# Walmart: uses curl_cffi (browser TLS fingerprinting) — no browser needed
python camoufox_scraper.py --store walmart

# Costco: uses Camoufox (stealth Firefox fork) — bypasses Akamai
python camoufox_scraper.py --store costco

# Both stores
python camoufox_scraper.py --all

# Single search with optional proxy
python camoufox_scraper.py --store walmart --query "chicken breast"
python camoufox_scraper.py --store walmart --proxy socks5://host:port
```

## Project Structure

```
calgary-grocery-scraper/
├── run_scraper.py              # Main entry point
├── camoufox_scraper.py         # Stealth scraper (Workshop Ch.7)
├── requirements.txt
├── scrapy.cfg
├── scrapers/
│   ├── settings.py             # Scrapy config + anti-detection
│   ├── items.py                # GroceryItem data model
│   ├── pipelines.py            # Clean, dedup, SQLite, CSV export
│   ├── middlewares/
│   │   ├── anti_detection.py   # Headers & fingerprint (Ch.2, 4, 5)
│   │   ├── user_agent_rotator.py  # UA rotation
│   │   └── smart_retry.py     # Exponential backoff (Ch.3)
│   └── spiders/
│       ├── walmart.py          # Walmart.ca API + Playwright
│       ├── superstore.py       # Loblaw PCX API
│       ├── saveonfoods.py      # Playwright SPA scraper
│       ├── nofrills.py         # Loblaw PCX API
│       └── safeway.py          # Playwright + Next.js
├── web/
│   ├── app.py                  # Flask price comparison UI
│   └── templates/
│       ├── base.html           # Layout with nav + styles
│       ├── index.html          # Home: deals, categories, search
│       ├── search.html         # Search results + comparison tables
│       ├── category.html       # Category browser
│       └── stats.html          # Scraping statistics
└── data/
    ├── grocery_prices.db       # SQLite database (auto-created)
    └── *_products.csv          # Per-store CSV exports
```

## Proxy Support (Scrapoxy)

For heavy scraping, set up Scrapoxy (Workshop Challenge 3):

```bash
docker run -p 8888:8888 -p 8890:8890 \
  -e AUTH_LOCAL_USERNAME=admin \
  -e AUTH_LOCAL_PASSWORD=password \
  -e BACKEND_JWT_SECRET=secret1 \
  -e FRONTEND_JWT_SECRET=secret2 \
  scrapoxy/scrapoxy:latest
```

Then uncomment the proxy settings in `scrapers/settings.py`.

## Tips

- All spiders use Playwright for JS rendering — sites are SPAs that require a real browser
- Loblaw stores (Superstore, No Frills) use identical `data-testid` selectors
- Walmart.ca has aggressive bot detection — use Camoufox or residential proxies
- Run scrapers during off-peak hours (late night) to reduce detection risk
- Clear old data with `python run_scraper.py --clear --all` for fresh prices
- CSS selectors may need updating as stores redesign their pages
