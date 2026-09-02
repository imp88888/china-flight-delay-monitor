import os
import random
import time
import requests
from cachetools import TTLCache

CACHE = TTLCache(maxsize=2000, ttl=int(os.getenv("SCRAPE_TTL", "120")))
UA_LIST = [u.strip() for u in os.getenv("SCRAPE_UA_LIST", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36,Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15").split(",")]


def request_with_retry(url, params=None, headers=None, timeout=10, retries=None):
    retries = int(retries or os.getenv("SCRAPE_RETRIES", "3"))
    cache_key = f"{url}|{params}"
    if cache_key in CACHE:
        return CACHE[cache_key]
    proxy = os.getenv("REQUESTS_PROXY")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    for i in range(retries):
        ua = random.choice(UA_LIST)
        h = dict(headers or {})
        h.setdefault("User-Agent", ua)
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout, proxies=proxies)
            if r.status_code == 200:
                CACHE[cache_key] = r.text
                return r.text
            if r.status_code in (429, 500, 502, 503, 504):
                backoff = (2 ** i) + random.random()
                time.sleep(backoff)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep((2 ** i) + random.random())
    raise RuntimeError(f"Failed to fetch {url}")
