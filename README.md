# Python Web Scraping Examples

Three production-style scraping programs, each demonstrating a different level of complexity:

| # | Program | Library | Target site | Use case |
|---|---------|---------|-------------|----------|
| 1 | `1_for simple sites.py` | `requests` + `BeautifulSoup` | [books.toscrape.com](https://books.toscrape.com) | Simple static HTML sites |
| 2 | `2_for JavaScript sites.py` | `selenium` | [quotes.toscrape.com/js](https://quotes.toscrape.com/js/) | JavaScript-rendered sites |
| 3 | `3_scraper_proxy_rotation.py` | `requests` + `BeautifulSoup` + proxy rotation | [books.toscrape.com](https://books.toscrape.com) | High-volume scraping at scale |

Every line of code is commented to explain what it does — these are meant as learning references as well as working scrapers.

> **Legal note:** These scripts target `books.toscrape.com` and `quotes.toscrape.com`, two sites explicitly built and maintained for scraping practice. If you point any of these programs at a different site, check that site's `robots.txt` and Terms of Service first, and scrape responsibly (rate-limit your requests, identify yourself honestly, and don't overload a server that hasn't agreed to it).

---

## Repository structure

```
.
├── 1_for simple sites.py         # Program 1: static site scraper
├── 2_for JavaScript sites.py          # Program 2: JS-rendered site scraper
├── 3_using proxy rotation.py    # Program 3: proxy-rotating, concurrent scraper
└── README.md                      # this file
```

## Requirements

- Python 3.10+
- Google Chrome (installed on your system) — required for Programs 2 and 3's Selenium usage
- pip

## Installation

Clone the repo and set up a virtual environment (recommended so these dependencies stay isolated from your system Python):

```bash
git clone <your-repo-url>
cd <your-repo-folder>

python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Or install the dependencies directly without the requirements file:

```bash
pip install requests beautifulsoup4 selenium webdriver-manager
```

If you're on Debian/Ubuntu and get an `externally-managed-environment` error, it means you're trying to install outside a virtual environment — use the `venv` steps above instead.

---

## Program 1 — BeautifulSoup (static sites)

```bash
python 1_scraper_beautifulsoup.py
```

**What it does:**
- Crawls every page of `books.toscrape.com`'s catalogue automatically (follows the "Next" pagination link until there isn't one)
- Extracts each book's title, price, star rating, and stock availability
- Retries failed requests up to 3 times with a short backoff
- Writes results to `books_data.csv`

**Adapt it to another site** by changing:
- `BASE_URL` / `START_URL`
- The CSS selectors inside `parse_book_card()` to match the target site's HTML

## Program 2 — Selenium (JavaScript-rendered sites)

```bash
python 2_scraper_selenium.py
```

**What it does:**
- Launches headless Chrome (no visible window) via `webdriver-manager`, which auto-downloads the matching chromedriver — no manual driver setup needed
- Waits for the page's JavaScript to actually render the quotes before reading them
- Clicks the "Next" button to page through the whole site
- Extracts each quote's text, author, and tags
- Writes results to `quotes_data.csv`

**Adapt it to another site** by changing:
- `START_URL`
- The `By.CLASS_NAME` / `By.CSS_SELECTOR` locators in `parse_current_page()` and `go_to_next_page()`

**Troubleshooting:** if Chrome fails to launch, confirm Google Chrome is installed and its version is compatible with the chromedriver `webdriver-manager` downloads (it should auto-match by default).

## Program 3 — Proxy rotation (large-scale scraping)

```bash
python 3_scraper_proxy_rotation.py
```

**What it does:**
- Fetches many pages concurrently using a thread pool (`MAX_WORKERS = 8` by default)
- Rotates through a pool of proxies and User-Agent strings on every request
- Automatically retires a proxy from the pool after 3 failures
- Retries failed requests with exponential backoff + jitter
- Saves progress to `checkpoint.json` after every page, so if the script crashes or is stopped, re-running it resumes instead of starting over
- Writes final results to `books_data_proxy.csv` and deletes the checkpoint on success

**Before running this one, edit the script:**

```python
PROXIES = [
    "http://user:pass@proxy1.yourprovider.com:8000",
    "http://user:pass@proxy2.yourprovider.com:8000",
    "http://user:pass@proxy3.yourprovider.com:8000",
]
```

Replace these with real proxies from a provider you legally pay for or are authorized to use. Free public proxy lists are unreliable and unsafe to route real traffic through — don't use them here.

You can also tune:
- `TOTAL_PAGES` — how many pages the target site has
- `MAX_WORKERS` — concurrency level
- `MAX_RETRIES` / `BASE_BACKOFF` — retry behavior

**Resuming after a crash:** just run the script again — it reads `checkpoint.json` and only fetches pages not already marked done.

---

## Output

Each program produces a CSV file in the same folder it's run from:

| Program | Output file |
|---|---|
| 1 | `books_data.csv` |
| 2 | `quotes_data.csv` |
| 3 | `books_data_proxy.csv` (+ temporary `checkpoint.json` while running) |

Open them with Excel, Google Sheets, `pandas.read_csv()`, or any CSV viewer.

## Notes on scaling to real production use

- Always add delays between requests when scraping a real business's site — the delays and concurrency caps in these scripts are intentional, not just style choices.
- Respect `robots.txt` and a site's Terms of Service before scraping it.
- Log everything (all three programs already do this) so you can diagnose failures without re-running blind.
- For sites that require login/session cookies, you'll need to extend Programs 1/2 to authenticate first and reuse the session/cookies on subsequent requests.

## License

Use and modify freely for your own projects.
