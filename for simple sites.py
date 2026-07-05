"""
PROGRAM 1 : Simple static-site scraper using Requests + BeautifulSoup
Target: https://books.toscrape.com  (a real, live site made for scraping practice,
no login, no JS-rendering needed, no anti-bot protection — perfect for BS4).

What it does:
- Crawls every page of the catalogue (pagination handled automatically)
- Extracts: title, price, star rating, stock availability, product URL
- Saves everything to a clean CSV file
- Uses retries, timeouts, delays and logging like a real production script
"""

import csv                                   # to write the scraped data into a .csv file
import logging                               # to print timestamped status/error messages
import time                                  # to pause between requests (politeness delay)
from urllib.parse import urljoin             # to safely combine a base URL with a relative link

import requests                              # to send HTTP requests and download HTML pages
from bs4 import BeautifulSoup                # to parse HTML and extract data with CSS selectors

# CONFIGURATION 
# change these values depending on the site you scrape

BASE_URL = "https://books.toscrape.com/"                     # root URL of the site
START_URL = urljoin(BASE_URL, "catalogue/page-1.html")        # first page of the catalogue
OUTPUT_FILE = "books_data.csv"                                # name of the CSV file to produce
REQUEST_DELAY = 1.0                                           # seconds to wait between requests (avoid overloading the server)
TIMEOUT = 10                                                  # max seconds to wait for a server response before giving up
MAX_RETRIES = 3                                               # how many times to retry a failed request before skipping it

HEADERS = {                                                    # HTTP headers sent with every request
    "User-Agent": (                                            # tells the server which "browser" is making the request
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",                       # tells the server we prefer English content
}

# ---------------------------------------------------------------------------
# LOGGING SETUP — production code should never use plain print()
# ---------------------------------------------------------------------------
logging.basicConfig(                          # configures how log messages look
    level=logging.INFO,                        # show INFO level and above (INFO, WARNING, ERROR)
    format="%(asctime)s [%(levelname)s] %(message)s",  # add timestamp + severity to each log line
)
logger = logging.getLogger(__name__)           # create a logger object specific to this script


def get_soup(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Download a page and return it parsed as a BeautifulSoup object, or None on failure."""
    for attempt in range(1, MAX_RETRIES + 1):              # try up to MAX_RETRIES times
        try:
            response = session.get(url, timeout=TIMEOUT)    # send the GET request with a timeout
            response.raise_for_status()                     # raise an error if status code is 4xx/5xx
            return BeautifulSoup(response.text, "html.parser")  # parse the HTML text into a soup object
        except requests.RequestException as exc:            # catch any network/HTTP-related error
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)  # log the failure
            time.sleep(REQUEST_DELAY * attempt)              # wait longer after each failed attempt (backoff)
    logger.error("Giving up on %s after %d attempts", url, MAX_RETRIES)  # log final failure
    return None                                              # return None so the caller can skip this page


def parse_book_card(card, session: requests.Session) -> dict:
    """Extract the fields we need from a single book's HTML block on the listing page."""
    title = card.h3.a["title"].strip()                       # the <a title="..."> attribute holds the full title
    relative_link = card.h3.a["href"]                         # relative URL to the book's own detail page
    product_url = urljoin(BASE_URL + "catalogue/", relative_link)  # turn it into a full absolute URL

    price_text = card.select_one(".price_color").text          # text of the element holding the price, e.g. "£51.77"
    price = float(price_text.replace("£", "").strip())          # strip currency symbol and convert to a number

    rating_class = card.select_one(".star-rating")["class"]     # classes look like ["star-rating", "Three"]
    rating_word = rating_class[-1]                              # the last class word is the rating in English
    rating_map = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}  # map word rating to an integer
    rating = rating_map.get(rating_word, 0)                     # convert to int, default 0 if unrecognised

    availability = card.select_one(".availability").text.strip()  # e.g. "In stock" or "Out of stock"

    return {                                                    # return a clean dictionary for this one book
        "title": title,
        "price_gbp": price,
        "rating_stars": rating,
        "availability": availability,
        "url": product_url,
    }


def scrape_all_books() -> list[dict]:
    """Walk through every catalogue page and collect every book's data."""
    results: list[dict] = []                                    # will hold one dict per scraped book
    session = requests.Session()                                # reuse one TCP connection across requests (faster)
    session.headers.update(HEADERS)                              # attach our custom headers to every request

    next_url = START_URL                                         # start crawling from page 1
    page_number = 1                                               # human-readable page counter for logging

    while next_url:                                               # loop until there is no "next page" link
        logger.info("Scraping page %d: %s", page_number, next_url)  # log progress
        soup = get_soup(session, next_url)                        # download and parse the current page
        if soup is None:                                         # if the page could not be downloaded
            break                                                  # stop the crawl instead of crashing

        book_cards = soup.select("article.product_pod")           # each book preview is one <article> tag
        for card in book_cards:                                    # loop over every book on this page
            try:
                results.append(parse_book_card(card, session))     # extract and store the book's data
            except (AttributeError, ValueError) as exc:             # if the HTML structure is unexpected
                logger.warning("Skipping a malformed book card: %s", exc)  # log and continue, don't crash

        next_link = soup.select_one("li.next a")                   # the "Next" pagination button, if it exists
        next_url = urljoin(next_url, next_link["href"]) if next_link else None  # build next URL or stop
        page_number += 1                                            # increase page counter
        time.sleep(REQUEST_DELAY)                                   # be polite: wait before the next request

    return results                                                  # give back the full list of scraped books


def save_to_csv(rows: list[dict], filename: str) -> None:
    """Write the scraped rows to a CSV file, ready to open in Excel/Sheets."""
    if not rows:                                                     # if nothing was scraped
        logger.warning("No data to save.")                          # warn instead of writing an empty/broken file
        return                                                       # exit the function early

    with open(filename, "w", newline="", encoding="utf-8") as f:      # open the file for writing text
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())         # writer that maps dict keys to CSV columns
        writer.writeheader()                                          # write the column names as the first row
        writer.writerows(rows)                                        # write every book as one CSV row

    logger.info("Saved %d rows to %s", len(rows), filename)           # confirm success in the logs


if __name__ == "__main__":                                            # only run this block when executed directly
    scraped_data = scrape_all_books()                                  # run the full crawl and get the results
    save_to_csv(scraped_data, OUTPUT_FILE)                              # persist the results to disk