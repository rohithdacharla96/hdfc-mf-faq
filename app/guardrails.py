import re

PII_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone": r"(?:\+91[\s-]?)?[6-9]\d{9}\b",
    "pan": r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b",
    "aadhaar": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "account": r"\b(?:account|a/c|acct)\s*(?:number|no\.?)?\s*[:#-]?\s*\d{9,18}\b",
    "otp": r"\b(?:otp|one[\s-]?time\s?password)\b.{0,20}\b\d{4,8}\b",
}

ADVICE = (
    "should i", "should we", "buy", "sell", "hold", "recommend",
    "better", "best", "worst", "worth it", "good", "bad", "safe",
    "risky", "suitable", "invest in", "portfolio", "allocate",
    "suggest", "advice", "which fund", "compare", "switch", "redeem",
)

PERFORMANCE = (
    "return", "returns", "cagr", "xirr", "profit", "loss",
    "performance", "outperform", "beat the market", "will it give",
    "will this", "will give", "expected return", "future value",
)

AMC_URL = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"

SCHEMES = [
    # Statement / capital-gains questions belong to the AMC page.
    (
        AMC_URL,
        ("capital gain", "capital gains", "statement", "account statement"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        ("elss", "tax saver", "lock-in", "lock in", "lockin"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        ("large cap", "large-cap"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
        ("flexi cap", "flexi", "equity fund"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        ("mid cap", "mid-cap"),
    ),
    # Generic AMC aliases come last so scheme names win.
    (AMC_URL, ("hdfc mutual fund", "hdfc mf", "amc")),
]


def _contains(term: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def has_pii(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in PII_PATTERNS.values())


def intent(text: str) -> str:
    q = " ".join(text.lower().split())
    if any(_contains(t, q) for t in PERFORMANCE):
        return "performance"
    if any(_contains(t, q) for t in ADVICE):
        return "advice"
    return "factual"


def detect_scheme(query: str) -> str | None:
    q = " ".join(query.lower().split())
    for url, aliases in SCHEMES:
        if any(_contains(alias, q) for alias in aliases):
            return url
    return None


# Fact kinds that map to one structured "Fund Details" section per scheme.
FACTS = [
    ("expense ratio", ("expense ratio", "expense", "ter", "total expense")),
    ("exit load", ("exit load", "exit-load", "redemption fee")),
    ("minimum sip", ("minimum sip", "min sip", "sip amount", "sip minimum", "sip")),
    ("lock-in", ("lock-in", "lock in", "lockin")),
    ("riskometer", ("riskometer", "risk level", "risk")),
    ("benchmark", ("benchmark", "tracking index", "index tracked")),
    ("aum", ("aum", "assets under management", "fund size")),
    ("nav", ("nav", "net asset value")),
    ("fund manager", ("fund manager", "managed by", "who manages")),
    ("registrar", ("registrar", "rta")),
    ("launch date", ("launch date", "inception date", "launched")),
    ("minimum investment", ("minimum investment", "min investment", "first investment")),
    ("minimum withdrawal", ("minimum withdrawal", "minimum redeem")),
    ("stamp duty", ("stamp duty",)),
    ("objective", ("investment objective", "scheme objective", "scheme seeks")),
]

SECTION_FOR_FACT = {
    "expense ratio": "Expense ratio",
    "exit load": "Exit load",
    "minimum sip": "Minimum SIP",
    "lock-in": "Lock-in period",
    "riskometer": "Riskometer",
    "benchmark": "Benchmark",
    "aum": "AUM",
    "nav": "NAV",
    "fund manager": "Fund manager",
    "registrar": "Registrar",
    "launch date": "Launch date",
    "minimum investment": "Minimum first investment",
    "minimum withdrawal": "Minimum withdrawal",
    "stamp duty": "Stamp duty",
    "objective": "Scheme objective",
}

STATEMENT_TERMS = ("statement", "capital gain", "capital gains", "account statement")


def detect_fact(query: str) -> str | None:
    q = " ".join(query.lower().split())
    for fact, aliases in FACTS:
        if any(_contains(alias, q) for alias in aliases):
            return fact
    return None


def is_statement_query(query: str) -> bool:
    q = " ".join(query.lower().split())
    return any(_contains(term, q) for term in STATEMENT_TERMS)


def is_scoped_query(query: str) -> bool:
    """True when the question is about these five pages or their facts."""
    q = " ".join(query.lower().split())
    return (
        detect_scheme(query) is not None
        or detect_fact(query) is not None
        or _contains("hdfc", q)
    )
