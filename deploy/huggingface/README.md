---
title: HDFC MF Facts Assistant
emoji: 💬
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Facts-only HDFC Mutual Fund FAQ assistant
suggested_hardware: cpu-basic
---

# HDFC MF Facts Assistant

A facts-only RAG assistant for five official HDFC Mutual Fund pages on Groww. It answers questions about expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and scheme metadata — and nothing else.

> **Facts-only. No investment advice.** This is an educational prototype, not a recommendation or an offer to buy or sell any scheme. Mutual fund investments are subject to market risks.

## What it does

- Answers only from the five scoped Groww pages and always shows exactly one source link.
- Adds a freshness line: `Last updated from sources: YYYY-MM-DD`.
- Keeps every answer to at most three sentences.
- Refuses buy/sell/advice, comparisons, return predictions, and performance questions.
- Rejects PAN, Aadhaar, account numbers, OTPs, emails, and phone numbers without storing the raw query.
- Returns an honest "not available in the scoped official pages" when a fact is absent.

## Sources

1. [HDFC Mutual Fund — AMC overview](https://groww.in/mutual-funds/amc/hdfc-mutual-funds)
2. [HDFC Large Cap Fund Direct Growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth)
3. [HDFC Flexi Cap Direct Plan Growth](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth)
4. [HDFC ELSS Tax Saver Fund Direct Plan Growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)
5. [HDFC Mid Cap Fund Direct Growth](https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth)

The scraper never follows, queues, or fetches links found inside these pages.

## How it works

`scrape → chunk → embed → index → retrieve → generate`

- Section-aware chunks capped at 180 words, with tables preserved.
- `sentence-transformers/all-MiniLM-L6-v2` embeddings (384-d).
- ChromaDB with cosine distance and a prebuilt index baked into the image.
- Groq LLM generation when `GROQ_API_KEY` is configured.
- Deterministic extractive fallback when the key is absent or the LLM fails.

## Configuration

| Setting | Where |
|---|---|
| Source URLs | `config.yaml` |
| Embedding model | `config.yaml` → `embedding.model` |
| Vector DB path/collection | `config.yaml` → `vector_db` |
| Retrieval depth/threshold | `config.yaml` → `retrieval` |
| LLM model | `GROQ_MODEL` environment variable |
| Groq key | `GROQ_API_KEY` Space secret |

The Space runs without a Groq key using the deterministic fallback.

## Notes and limits

- The five scoped pages do not contain capital-gains-statement download instructions, so those questions return not-found rather than an invented answer.
- Chat history is stored in the visitor's browser (`localStorage`); the server does not keep user conversations.
- This is a prototype built for a learning exercise. Always verify current facts on the official Groww/AMC pages.
