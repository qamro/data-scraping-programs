"""
PROGRAM 2 : JavaScript-rendered site scraper using Selenium
Target: https://quotes.toscrape.com/js/  (a real, live site that renders its quotes
with JavaScript after the page loads — plain requests+BeautifulSoup would see an
empty page, so a real browser engine is required).

What it does:
- Launches a real (headless) Chrome browser
- Waits for the JS-rendered content to actually appear before reading it
- Extracts: quote text, author, tags
- Clicks "Next" through every page automatically
- Saves everything to a CSV file
- Closes the browser cleanly even if something crashes (production safety)
"""

import csv                                                  # to write the scraped data to a CSV file
import logging                                               # to log progress/errors with timestamps
import time                                                  # to add small polite delays between pages

from selenium import webdriver                               # controls the actual browser
from selenium.webdriver.chrome.options import Options         # to configure Chrome (e.g. headless mode)
from selenium.webdriver.chrome.service import Service         # to manage the chromedriver executable
from selenium.webdriver.common.by import By                   # provides ways to locate elements (CSS, XPATH...)
from selenium.webdriver.support.ui import WebDriverWait        # waits until a condition becomes true
from selenium.webdriver.support import expected_conditions as EC  # ready-made wait conditions
from selenium.common.exceptions import (                       # specific Selenium errors we want to catch
    TimeoutException,
    NoSuchElementException,
)
from webdriver_manager.chrome import ChromeDriverManager        # auto-downloads the right chromedriver version

# CONFIGURATION

START_URL = "https://quotes.toscrape.com/js/"    # the JS-rendered version of the site
OUTPUT_FILE = "quotes_data.csv"                  # output CSV filename
PAGE_LOAD_TIMEOUT = 15                            # max seconds to wait for the page/elements to load
PAGE_DELAY = 1.0                                  # polite delay between pages, in seconds

logging.basicConfig(                              # configure the logging format
    level=logging.INFO,                           # show INFO and above
    format="%(asctime)s [%(levelname)s] %(message)s",  # timestamp + level + message
)
logger = logging.getLogger(__name__)               # logger instance for this script


def build_driver() -> webdriver.Chrome:
    """Create and configure a headless Chrome driver ready for production use."""
    options = Options()                                        # container for Chrome startup options
    options.add_argument("--headless=new")                     # run Chrome with no visible window (server-friendly)
    options.add_argument("--disable-gpu")                       # disable GPU rendering, not needed headless
    options.add_argument("--no-sandbox")                        # required when running as root / in containers
    options.add_argument("--disable-dev-shm-usage")             # avoid crashes from limited /dev/shm in containers
    options.add_argument("--window-size=1920,1080")             # set a realistic viewport size
    options.add_argument(                                        # set a realistic desktop User-Agent string
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())          # download/locate the matching chromedriver binary
    driver = webdriver.Chrome(service=service, options=options)  # launch the actual Chrome browser instance
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)               # cap how long a full page load can take
    return driver                                                 # hand back the ready-to-use driver


def wait_for_quotes(driver: webdriver.Chrome) -> None:
    """Block execution until at least one quote element has been rendered by JS."""
    WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(               # wait up to PAGE_LOAD_TIMEOUT seconds
        EC.presence_of_element_located((By.CLASS_NAME, "quote"))  # ...until a ".quote" element exists in the DOM
    )


def parse_current_page(driver: webdriver.Chrome) -> list[dict]:
    """Extract all quotes visible on the currently loaded page."""
    rows = []                                                      # will hold one dict per quote on this page
    quote_elements = driver.find_elements(By.CLASS_NAME, "quote")  # find every rendered quote block

    for quote_el in quote_elements:                                 # loop through each quote block
        text = quote_el.find_element(By.CLASS_NAME, "text").text     # the quote sentence itself
        author = quote_el.find_element(By.CLASS_NAME, "author").text  # the author's name
        tag_elements = quote_el.find_elements(By.CLASS_NAME, "tag")   # list of tag <a> elements, may be empty
        tags = [tag.text for tag in tag_elements]                     # extract text of each tag into a list

        rows.append({                                                  # store this quote as a dictionary
            "quote": text,
            "author": author,
            "tags": ", ".join(tags),                                   # join tags into one string for CSV
        })

    return rows                                                        # give back all quotes found on this page


def go_to_next_page(driver: webdriver.Chrome) -> bool:
    """Click the 'Next' button if it exists. Return False when there is no next page (end of site)."""
    try:
        next_button = driver.find_element(By.CSS_SELECTOR, "li.next > a")  # locate the "Next" link
    except NoSuchElementException:                                     # if it isn't found on the page
        return False                                                    # signal that we've reached the last page

    next_button.click()                                                # simulate a real click on the button
    try:
        wait_for_quotes(driver)                                        # wait for the new page's JS to render
    except TimeoutException:                                           # if the new page never loads in time
        logger.warning("Timed out waiting for next page to render.")   # log the issue
        return False                                                    # stop the crawl safely
    return True                                                          # signal that we moved to a new page


def scrape_all_quotes() -> list[dict]:
    """Full crawl: open the site, page through it, and collect every quote."""
    all_rows: list[dict] = []                                           # accumulator for every quote scraped
    driver = build_driver()                                              # start the headless browser

    try:                                                                  # wrap everything so we always close the browser
        driver.get(START_URL)                                            # navigate to the first page
        page_number = 1                                                   # counter for logging

        while True:                                                       # loop until there's no next page
            logger.info("Scraping page %d", page_number)                 # log progress
            wait_for_quotes(driver)                                       # ensure JS content has rendered
            all_rows.extend(parse_current_page(driver))                   # scrape this page and add to results

            has_next = go_to_next_page(driver)                            # try to move to the next page
            if not has_next:                                              # if there was no next page
                break                                                      # end the crawl loop
            page_number += 1                                               # increment page counter
            time.sleep(PAGE_DELAY)                                        # polite pause before scraping next page

    finally:
        driver.quit()                                                     # always close the browser, even on error

    return all_rows                                                        # return everything we collected


def save_to_csv(rows: list[dict], filename: str) -> None:
    """Write scraped quotes to a CSV file."""
    if not rows:                                                           # nothing scraped?
        logger.warning("No data to save.")                                # warn and stop
        return

    with open(filename, "w", newline="", encoding="utf-8") as f:            # open file for text writing
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())               # map dict keys to CSV columns
        writer.writeheader()                                                # write column headers
        writer.writerows(rows)                                              # write every quote as a row

    logger.info("Saved %d rows to %s", len(rows), filename)                 # confirm success


if __name__ == "__main__":                                                  # run only when executed directly
    scraped_data = scrape_all_quotes()                                      # perform the full scrape
    save_to_csv(scraped_data, OUTPUT_FILE)                                   # save results to disk