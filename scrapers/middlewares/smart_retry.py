"""
Smart Retry Middleware
Handles 403/429 with exponential backoff + jitter.
(Workshop Challenge 3: Rate limit bypass)
"""

import random
import time
import logging
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message

logger = logging.getLogger(__name__)


class SmartRetryMiddleware(RetryMiddleware):
    """Extends Scrapy's RetryMiddleware with exponential backoff."""

    def process_response(self, request, response, **kwargs):
        if response.status in (403, 429, 503):
            retry_count = request.meta.get("retry_times", 0)
            # Exponential backoff: 2^retry * (1 + random jitter)
            delay = min((2 ** retry_count) * (1 + random.random()), 60)
            logger.info(
                f"[SmartRetry] Got {response.status} — waiting {delay:.1f}s "
                f"before retry #{retry_count + 1} for {request.url}"
            )
            time.sleep(delay)
            reason = response_status_message(response.status)
            return self._retry(request, reason, **kwargs) or response

        return super().process_response(request, response, **kwargs)
