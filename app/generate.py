import json
import os
import re

from app.config import CONFIG

BANNED = (
    "recommend", "guaranteed", "guarantee", "best fund", "will give",
    "outperform", "beat the market", "sure shot", "risk-free", "assured return",
)


def _client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set in .env")
    from groq import Groq

    return Groq(api_key=key)


def build_context(rows: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] source_url: {r['source_url']}\n"
        f"section: {r['section']}\n{r['text']}"
        for i, r in enumerate(rows, 1)
    )


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object in model response")
    return json.loads(text[start : end + 1])


def clean_body(text: str) -> str:
    """Remove URLs/source lines and cap the factual body at 3 sentences."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?im)^\s*(source|last updated from sources)\s*:.*$", "", text)
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:3]).strip()


def _fact_line(text: str) -> str:
    """Turn a retrieved 'label | value' chunk into one readable sentence."""
    text = " ".join(text.split()).rstrip(".")
    if " | " in text:
        label, value = text.split(" | ", 1)
        if value.lower().startswith(label.lower()):
            # "Exit load | Exit load of 1% ..." -> "Exit load of 1% ..."
            return f"{value[0].upper()}{value[1:]}."
        return f"{label}: {value}."
    if text and text[-1] not in ".!?":
        text += "."
    return text


def fallback_answer(rows: list[dict]) -> dict:
    body = _fact_line(rows[0]["text"]) if rows else ""
    body = clean_body(body)
    if not body:
        body = "That fact is not available in the scoped official pages."
    return {"answer": body, "citation_url": rows[0]["source_url"] if rows else ""}


def generate(question: str, rows: list[dict]) -> dict:
    model = CONFIG["llm"]["model"].strip()
    if not model:
        raise RuntimeError("GROQ_MODEL is not set in .env")

    prompt = f"""You are a facts-only mutual fund FAQ assistant.
Use ONLY the context below. Do not use outside knowledge.
Answer the exact fact asked, in at most 3 sentences.
Never give advice, recommendations, opinions, comparisons, or return predictions.
If the context does not contain the answer, say it is not available in the scoped official pages.
Do not put URLs in the answer.
Return JSON only: {{"answer": "...", "citation_url": "..."}}.
citation_url must be one of the context source URLs.

Context:
{build_context(rows)}

Question: {question}"""

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": CONFIG["llm"]["temperature"],
        "max_tokens": CONFIG["llm"]["max_tokens"],
    }

    try:
        response = _client().chat.completions.create(
            **kwargs, response_format={"type": "json_object"}
        )
    except Exception as exc:
        # Some Groq models do not support JSON mode; retry once without it.
        if "response_format" not in str(exc).lower() and "json" not in str(exc).lower():
            raise
        response = _client().chat.completions.create(**kwargs)

    data = _parse_json(response.choices[0].message.content or "")
    answer = str(data.get("answer", "")).strip()
    if not answer:
        raise ValueError("Empty answer from model")

    allowed = {r["source_url"].rstrip("/") for r in rows}
    citation = str(data.get("citation_url", "")).strip().rstrip("/")
    if citation not in allowed:
        citation = rows[0]["source_url"]

    return {
        "answer": answer,
        "citation_url": citation,
        "prompt": prompt,
        "raw_llm_response": response.choices[0].message.content or "",
    }
