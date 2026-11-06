# Source List

## Primary corpus — scraped, indexed, and the only URLs ever cited

These are the five pages allowed by the brief. They are the only pages the scraper requests, the only pages in the vector store, and the only URLs that can appear in an answer.

| # | Page | URL | Facts used in answers |
|---|---|---|---|
| 1 | HDFC Mutual Fund — AMC overview | https://groww.in/mutual-funds/amc/hdfc-mutual-funds | AMC overview, investment process, fund-house context |
| 2 | HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth | Expense ratio, exit load, minimum SIP, riskometer, benchmark, lock-in, AUM, manager |
| 3 | HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth | Expense ratio, exit load, minimum SIP, riskometer, benchmark, lock-in, AUM, manager |
| 4 | HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth | Expense ratio, exit load, minimum SIP, riskometer, benchmark, 3-year ELSS lock-in |
| 5 | HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth | Expense ratio, exit load, minimum SIP, riskometer, benchmark, lock-in, AUM, manager |

**Rule enforced in code:** `app/config.py` raises if `config.yaml` does not contain exactly five URLs. `app/scrape.py` iterates only that list and never parses `<a href>` into new requests.

## Official reference pages — not scraped, not indexed, never cited

The brief asks for a 15–25 URL source list while also restricting scraping and citation to the five supplied pages. To honour the stricter rule, only rows 1–5 are part of the RAG corpus. The official pages below are listed for reviewer context and were deliberately **not fetched, not indexed, and not used to generate answers**.

| # | Organisation | URL |
|---|---|---|
| 6 | HDFC Asset Management Company | https://www.hdfcfund.com/ |
| 7 | HDFC Mutual Fund schemes | https://www.hdfcfund.com/mutual-funds |
| 8 | HDFC Mutual Fund investor services | https://www.hdfcfund.com/investor-services |
| 9 | SEBI | https://www.sebi.gov.in/ |
| 10 | SEBI investor education | https://investor.sebi.gov.in/ |
| 11 | AMFI | https://www.amfiindia.com/ |
| 12 | AMFI investor corner | https://www.amfiindia.com/investor-corner |
| 13 | Groww mutual fund hub | https://groww.in/mutual-funds |
| 14 | Groww HDFC Mutual Fund hub | https://groww.in/mutual-funds/hdfc-mutual-funds |
| 15 | Groww AMC directory | https://groww.in/mutual-funds/amc |

## Citation policy

- Every answer contains exactly one `Source:` link drawn from the retrieved context.
- The validator replaces any model-invented citation with the top retrieved chunk's URL.
- Body URLs are stripped, so the appended `Source:` line is the only link in a response.
- Statement-download questions cite the AMC page (row 1) and explicitly say the fact is not available in the scoped pages.
