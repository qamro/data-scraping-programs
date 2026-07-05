"""
Large-scale scraper with automatic proxy rotation
Target: https://books.toscrape.com (same real site as Program 1, but this version
is built to survive high request volume: rotating proxies, rotating User-Agents,
automatic retries/backoff, concurrent workers, and resumable checkpoints).

IMPORTANT : before you run this at scale:
1. Replace PROXIES below with real proxies from a proxy provider YOU pay for /
   are legally allowed to use. Free public proxy lists are unreliable and
   sometimes malicious — never scrape credentials/business logic through them.
2. Always check the target site's robots.txt and Terms of Service. This script
   adds delays and respects a max concurrency on purpose — please don't remove
   that to hammer a site harder than its owner allows.

What it does:
- Keeps a pool of proxies and cycles through them request by request
- Automatically removes a proxy from the pool if it fails repeatedly (dead/banned)
- Rotates User-Agent strings so requests don't all look identical
- Retries failed requests with exponential backoff
- Runs several workers in parallel with a thread pool for real throughput
- Saves progress to a checkpoint file so a crash/restart doesn't repeat work
"""

import csv                                            # to write final results to CSV
import itertools                                       # to build an infinite round-robin cycle over proxies
import json                                            # to read/write the checkpoint file
import logging                                         # for timestamped production-style logging
import os                                              # to check whether a checkpoint file already exists
import random                                          # to randomise delay and User-Agent choice
import threading                                       # to make the proxy pool thread-safe
import time                                            # for delays and backoff timing
from concurrent.futures import ThreadPoolExecutor, as_completed  # to run requests concurrently
from urllib.parse import urljoin                       # to build absolute URLs from relative links

import requests                                        # to perform the actual HTTP requests
from bs4 import BeautifulSoup                          # to parse the returned HTML

# CONFIGURATION

BASE_URL = "https://books.toscrape.com/"                 # root URL of the target site
TOTAL_PAGES = 50                                         # how many catalogue pages this site has (known in advance)
OUTPUT_FILE = "books_data_proxy.csv"                     # final CSV output
CHECKPOINT_FILE = "checkpoint.json"                      # stores which pages are already done
MAX_WORKERS = 8                                          # how many pages to fetch in parallel
MAX_RETRIES = 4                                          # retries per page before marking it as failed
TIMEOUT = 10                                             # seconds before a single request gives up
BASE_BACKOFF = 1.5                                       # base seconds for exponential backoff between retries

# Replace with your own real, paid/legal proxies, format: "http://user:pass@ip:port"
PROXIES = [
    "http://user:pass@proxy1.yourprovider.com:8000",
    "http://user:pass@proxy2.yourprovider.com:8000",
    "http://user:pass@proxy3.yourprovider.com:8000",
]

USER_AGENTS = [                                          # pool of realistic browser User-Agent strings
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
]

logging.basicConfig(                                       # configure log formatting
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s",  # include thread name (useful with workers)
)
logger = logging.getLogger(__name__)                        # logger for this module


class ProxyPool:
    """Thread-safe round-robin proxy pool that can permanently drop dead proxies."""

    def __init__(self, proxies: list[str]):
        self._lock = threading.Lock()                        # protects shared state across worker threads
        self._alive = list(proxies)                          # working copy of proxies still considered usable
        self._cycle = itertools.cycle(self._alive)            # infinite round-robin iterator over alive proxies

    def get(self) -> str | None:
        """Return the next proxy in rotation, or None if the pool is empty."""
        with self._lock:                                      # only one thread touches the cycle at a time
            if not self._alive:                                # if every proxy has been removed
                return None                                     # signal that we have nothing left to use
            return next(self._cycle)                            # return the next proxy in the rotation

    def remove(self, proxy: str) -> None:
        """Permanently drop a proxy that has failed too many times."""
        with self._lock:                                       # lock before mutating shared state
            if proxy in self._alive:                            # avoid double-removal errors
                self._alive.remove(proxy)                        # drop it from the usable list
                self._cycle = itertools.cycle(self._alive)        # rebuild the cycle without the dead proxy
                logger.warning("Removed dead proxy %s (%d left)", proxy, len(self._alive))  # log the removal


proxy_pool = ProxyPool(PROXIES)                               # single shared proxy pool for all worker threads


def fetch_page(page_number: int) -> tuple[int, str | None]:
    """Download one catalogue page using a rotated proxy + User-Agent, with retries."""
    url = urljoin(BASE_URL, f"catalogue/page-{page_number}.html")  # build this page's full URL

    for attempt in range(1, MAX_RETRIES + 1):                   # try this page up to MAX_RETRIES times
        proxy = proxy_pool.get()                                # grab the next proxy from the rotation
        if proxy is None:                                        # if the whole pool has died
            logger.error("No proxies left, aborting page %d", page_number)  # log fatal condition
            return page_number, None                              # give up on this page

        headers = {"User-Agent": random.choice(USER_AGENTS)}     # pick a random User-Agent for this attempt
        proxies_dict = {"http": proxy, "https": proxy}            # requests needs proxies keyed by protocol

        try:
            response = requests.get(                               # perform the actual HTTP GET request
                url,
                headers=headers,
                proxies=proxies_dict,
                timeout=TIMEOUT,
            )
            if response.status_code == 429 or response.status_code >= 500:  # rate-limited or server error
                raise requests.RequestException(f"Bad status {response.status_code}")  # treat as a failure to retry
            response.raise_for_status()                            # raise on any other 4xx error
            return page_number, response.text                      # success: return the page number + HTML

        except requests.RequestException as exc:                   # any network/proxy/HTTP failure
            logger.warning(                                         # log this specific failed attempt
                "Page %d attempt %d/%d via %s failed: %s",
                page_number, attempt, MAX_RETRIES, proxy, exc,
            )
            failure_count = getattr(fetch_page, f"_fail_{proxy}", 0) + 1  # track failures per proxy on the function object
            setattr(fetch_page, f"_fail_{proxy}", failure_count)          # persist the updated failure count
            if failure_count >= 3:                                       # if this proxy has failed 3+ times total
                proxy_pool.remove(proxy)                                  # permanently retire it from the pool
            time.sleep(BASE_BACKOFF * (2 ** (attempt - 1)) + random.random())  # exponential backoff + jitter

    logger.error("Page %d failed after %d attempts", page_number, MAX_RETRIES)  # log final failure for this page
    return page_number, None                                                 # give up, return no HTML


def parse_page(html: str) -> list[dict]:
    """Extract book data from one page's raw HTML (same logic as Program 1)."""
    soup = BeautifulSoup(html, "html.parser")                    # parse the HTML string into a soup object
    rows = []                                                      # collected book dicts for this page

    for card in soup.select("article.product_pod"):                # loop over every book preview block
        title = card.h3.a["title"].strip()                          # full book title from the title attribute
        price = float(card.select_one(".price_color").text.replace("£", ""))  # numeric price
        rating_word = card.select_one(".star-rating")["class"][-1]   # rating word, e.g. "Four"
        rating_map = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}  # word-to-number mapping
        availability = card.select_one(".availability").text.strip()  # stock status text

        rows.append({                                                 # store this book's data
            "title": title,
            "price_gbp": price,
            "rating_stars": rating_map.get(rating_word, 0),
            "availability": availability,
        })

    return rows                                                       # return all books found on this page


def load_checkpoint() -> dict:
    """Load previously completed pages/results so a restart doesn't redo work."""
    if os.path.exists(CHECKPOINT_FILE):                              # if a checkpoint file already exists
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:       # open it for reading
            return json.load(f)                                       # parse and return its JSON content
    return {"done_pages": [], "rows": []}                              # otherwise start with an empty state


def save_checkpoint(state: dict) -> None:
    """Persist current progress to disk so it survives a crash or manual stop."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:            # open checkpoint file for writing
        json.dump(state, f)                                             # dump current state as JSON


def scrape_all_pages_concurrently() -> list[dict]:
    """Fetch every page in parallel using a thread pool, honoring the checkpoint."""
    state = load_checkpoint()                                          # resume from any previous progress
    done_pages = set(state["done_pages"])                                # pages already completed, as a set
    all_rows = state["rows"]                                             # rows already collected previously

    pages_to_fetch = [p for p in range(1, TOTAL_PAGES + 1) if p not in done_pages]  # remaining work only
    logger.info("Resuming: %d pages already done, %d remaining", len(done_pages), len(pages_to_fetch))  # status log

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:         # create a pool of worker threads
        futures = {executor.submit(fetch_page, p): p for p in pages_to_fetch}  # schedule all remaining pages

        for future in as_completed(futures):                              # process results as they finish (any order)
            page_number, html = future.result()                            # unpack this page's result
            if html:                                                        # if the page was fetched successfully
                page_rows = parse_page(html)                                 # extract its book data
                all_rows.extend(page_rows)                                   # add to the overall results
                done_pages.add(page_number)                                  # mark this page as completed

            state = {"done_pages": sorted(done_pages), "rows": all_rows}      # rebuild the current state
            save_checkpoint(state)                                            # persist progress after every page

    return all_rows                                                            # return everything collected so far


def save_to_csv(rows: list[dict], filename: str) -> None:
    """Write final results to a CSV file."""
    if not rows:                                                              # nothing to write?
        logger.warning("No data to save.")                                    # warn and exit
        return

    with open(filename, "w", newline="", encoding="utf-8") as f:               # open output file
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())                  # map dict keys to CSV columns
        writer.writeheader()                                                    # write column headers
        writer.writerows(rows)                                                  # write every row

    logger.info("Saved %d rows to %s", len(rows), filename)                     # confirm success


if __name__ == "__main__":                                                       # run only when executed directly
    scraped_data = scrape_all_pages_concurrently()                               # run the full concurrent scrape
    save_to_csv(scraped_data, OUTPUT_FILE)                                        # write final CSV
    if os.path.exists(CHECKPOINT_FILE):                                          # cleanup: remove checkpoint on success
        os.remove(CHECKPOINT_FILE)                                                # so a future run starts fresh