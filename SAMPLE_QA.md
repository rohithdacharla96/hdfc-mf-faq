# Sample Q&A

These are real responses from the running API (`POST /api/ask`) against the indexed five-page corpus. The latest ingestion date is **2026-11-05**.

> No `GROQ_API_KEY` was available during verification, so the deterministic extractive fallback produced the factual bodies below. With a valid key, Groq rephrases the same retrieved fact; the `Source:` URL, the three-sentence cap, and the `Last updated from sources:` line do not change.

---

### 1. Expense ratio — HDFC Large Cap Fund

**Q:** What is the expense ratio of HDFC Large Cap Fund?

**A:**

> Expense ratio: 1.02%.
>
> Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
> Last updated from sources: 2026-11-05

---

### 2. Exit load — HDFC Mid Cap Fund

**Q:** What is the exit load for HDFC Mid Cap Fund?

**A:**

> Exit load of 1% if redeemed within 1 year.
>
> Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
> Last updated from sources: 2026-11-05

---

### 3. Exit load — HDFC ELSS Tax Saver Fund

**Q:** What is the exit load for HDFC ELSS Tax Saver Fund?

**A:**

> Exit load: Nil.
>
> Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-11-05

---

### 4. Minimum SIP — HDFC ELSS Tax Saver Fund

**Q:** What is the minimum SIP for HDFC ELSS Tax Saver Fund?

**A:**

> Minimum SIP: 500 rupees.
>
> Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-11-05

---

### 5. ELSS lock-in

**Q:** What is the ELSS lock-in period?

**A:**

> Lock-in period: 3 years.
>
> Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-11-05

---

### 6. Riskometer — HDFC Large Cap Fund

**Q:** What is the riskometer of HDFC Large Cap Fund?

**A:**

> Riskometer: Very High.
>
> Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
> Last updated from sources: 2026-11-05

---

### 7. Benchmark — HDFC Mid Cap Fund

**Q:** What is the benchmark of HDFC Mid Cap Fund?

**A:**

> Benchmark: NIFTY Midcap 150 Total Return Index.
>
> Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
> Last updated from sources: 2026-11-05

---

### 8. Statement download — honest not-found

**Q:** How do I download my capital gains statement?

**A:**

> That fact is not available in the scoped official pages. You can review the page linked below.
>
> Source: https://groww.in/mutual-funds/amc/hdfc-mutual-funds
> Last updated from sources: 2026-11-05

The five allowed pages contain no statement-download instructions, so the assistant refuses to invent one. It routes the user to the official AMC page instead.

---

### 9. Advice — polite refusal

**Q:** Should I buy HDFC Mid Cap Fund?

**A:**

> I can only share factual scheme information and can't offer investment advice. You can review the official page linked below.
>
> Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
> Last updated from sources: 2026-11-05

---

### 10. PII — privacy refusal

**Q:** My PAN is ABCDE1234F

**A:**

> I can't accept or store personal information such as PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers. You can review the official page linked below.
>
> Source: https://groww.in/mutual-funds/amc/hdfc-mutual-funds
> Last updated from sources: 2026-11-05

The raw query is not written to `data/traces/` for PII cases; the trace stores only `intent: "pii"`, the refusal, and the citation.
