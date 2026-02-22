"""
Anti-Detection Middleware
Implements techniques from the WebScraping Anti-Ban Workshop:
- Challenge 2: Realistic HTTP headers
- Challenge 4: Browser fingerprint consistency
- Challenge 5: Timezone/locale consistency
"""

import random
import logging

logger = logging.getLogger(__name__)


class AntiDetectionMiddleware:
    """Adds anti-detection headers and behaviours to every request."""

    # Realistic Referers for each store
    REFERERS = {
        "walmart": "https://www.google.ca/search?q=walmart+grocery+calgary",
        "superstore": "https://www.google.ca/search?q=real+canadian+superstore+calgary",
        "saveonfoods": "https://www.google.ca/search?q=save+on+foods+calgary",
        "nofrills": "https://www.google.ca/search?q=no+frills+calgary",
        "safeway": "https://www.google.ca/search?q=safeway+calgary",
        "costco": "https://www.google.ca/search?q=costco+grocery+calgary",
        "voila": "https://www.google.ca/search?q=voila+safeway+calgary",
    }

    # Sec-CH-UA headers to match Chrome 131
    SEC_CH_UA = '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"'

    def process_request(self, request, **kwargs):
        # Add realistic browser headers (Workshop Challenge 2)
        request.headers.setdefault(b"Sec-Ch-Ua", self.SEC_CH_UA)
        request.headers.setdefault(b"Sec-Ch-Ua-Mobile", "?0")
        request.headers.setdefault(b"Sec-Ch-Ua-Platform", '"Windows"')
        request.headers.setdefault(b"DNT", "1")

        # Add per-store referer — use request URL to detect store
        url = request.url.lower()
        for store_key, referer in self.REFERERS.items():
            if store_key in url:
                request.headers.setdefault(b"Referer", referer)
                break
        else:
            request.headers.setdefault(
                b"Referer", "https://www.google.ca/"
            )

        # Randomize Accept-Language slightly for fingerprint variance
        langs = [
            "en-CA,en-US;q=0.9,en;q=0.8",
            "en-CA,en;q=0.9",
            "en-US,en-CA;q=0.9,en;q=0.8,fr-CA;q=0.7",
        ]
        request.headers[b"Accept-Language"] = random.choice(langs)

        return None

    def process_response(self, request, response, **kwargs):
        # Log blocked responses for debugging
        if response.status in (403, 429):
            logger.warning(
                f"[AntiDetection] Blocked ({response.status}) on {request.url}"
            )
        return response
