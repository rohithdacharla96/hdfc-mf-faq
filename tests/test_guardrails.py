from app.guardrails import (
    AMC_URL,
    detect_fact,
    detect_scheme,
    has_pii,
    intent,
    is_statement_query,
)

ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
LARGE_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
MID_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"


def test_pii_rejected():
    assert has_pii("My PAN is ABCDE1234F")
    assert has_pii("email me at test@example.com")
    assert has_pii("call me on 9876543210")
    assert has_pii("aadhaar 1234 5678 9012")
    assert has_pii("account number 123456789012")
    assert has_pii("OTP is 123456")


def test_normal_factual_query_is_not_pii():
    assert not has_pii("What is the ELSS lock-in period?")
    assert not has_pii("What is the expense ratio of HDFC Mid Cap Fund?")


def test_normal_factual_query_passes_intent_guard():
    assert intent("What is the ELSS lock-in period?") == "factual"
    assert intent("What is the expense ratio of HDFC Large Cap Fund?") == "factual"


def test_advice_refused():
    assert intent("Should I buy HDFC Mid Cap Fund?") == "advice"
    assert intent("Which fund is better?") == "advice"
    assert intent("Is this fund good for me?") == "advice"


def test_performance_refused():
    assert intent("What returns will this fund give?") == "performance"
    assert intent("What is the 3-year CAGR?") == "performance"


def test_statement_routes_to_amc():
    assert detect_scheme("How do I download my capital gains statement?") == AMC_URL


def test_elss_lock_in_routes_to_elss():
    assert detect_scheme("What is the ELSS lock-in period?") == ELSS_URL


def test_scheme_names_beat_generic_amc_alias():
    assert detect_scheme("HDFC Mutual Fund large cap expense ratio") == LARGE_URL
    assert detect_scheme("HDFC mid cap exit load") == MID_URL


def test_detect_fact_maps_supported_questions():
    assert detect_fact("What is the expense ratio of HDFC Large Cap Fund?") == "expense ratio"
    assert detect_fact("What is the exit load for HDFC Mid Cap Fund?") == "exit load"
    assert detect_fact("What is the minimum SIP for HDFC ELSS?") == "minimum sip"
    assert detect_fact("What is the ELSS lock-in period?") == "lock-in"
    assert detect_fact("What is the riskometer of HDFC Large Cap Fund?") == "riskometer"
    assert detect_fact("What is the benchmark of HDFC Mid Cap Fund?") == "benchmark"


def test_detect_fact_returns_none_for_unsupported_questions():
    assert detect_fact("Who regulates mutual funds in India?") is None
    assert detect_fact("What is a mutual fund?") is None


def test_statement_query_detection():
    assert is_statement_query("How do I download my capital gains statement?")
    assert is_statement_query("I need my account statement")
    assert not is_statement_query("What is the expense ratio of HDFC Large Cap Fund?")
