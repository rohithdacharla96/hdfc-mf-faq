# Disclaimer

## Exact UI snippet

The assistant displays this line at the bottom of the page:

> **Facts-only. No investment advice.**

It is rendered by `ui/index.html`:

```html
<p class="note"><strong>Facts-only. No investment advice.</strong></p>
```

## Expanded disclaimer

This is an educational facts-only prototype built from five public Groww pages about HDFC Mutual Fund schemes. It is **not investment advice**, not a recommendation, and not a substitute for the official scheme documents.

- Answers are limited to factual fields such as expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, AUM, NAV date, fund manager, and registrar.
- The assistant refuses buy/sell/hold, portfolio, comparison, suitability, and return/performance questions.
- The assistant does not compute, compare, or predict returns, and it does not reproduce performance figures.
- Every answer carries exactly one official source URL from the scoped five-page corpus and a `Last updated from sources:` date.
- Facts can change. Always verify the current value on the linked official page before acting.
- Do not enter PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers. The assistant refuses such inputs and does not store the raw query.

## Citation and freshness

The `Last updated from sources:` date comes from `data/manifest.json`, which is written by `python -m app.index`. Re-run the four ingestion commands to refresh it:

```powershell
python -m app.scrape
python -m app.chunk
python -m app.embed
python -m app.index
```
