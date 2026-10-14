from __future__ import annotations

import pytest
from groundedness import numeric_facts, unsupported_numeric_facts

OCT_1_2026 = frozenset({"date:2026-10-01", "md:10-1", "2026"})

# ---------------------------------------------------------------------------- extraction


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        # numbers: thousands separators and scale words collapse to one value
        ("10,000", {"10000"}),
        ("10000", {"10000"}),
        ("10k", {"10000"}),
        ("10 thousand", {"10000"}),
        ("SGD 2.5 million", {"2500000"}),
        ("2.5M", {"2500000"}),
        ("2,500,000", {"2500000"}),
        # percentages
        ("18%", {"18%"}),
        ("18 percent", {"18%"}),
        # dates with a year
        ("2026-10-01", OCT_1_2026),
        ("1 October 2026", OCT_1_2026),
        ("Oct 1st, 2026", OCT_1_2026),
        ("October 1, 2026", OCT_1_2026),
        ("15th of October 2026", {"date:2026-10-15", "md:10-15", "2026"}),
        # dates without a year
        ("15 October", {"md:10-15"}),
        ("Oct 15", {"md:10-15"}),
        # ISO date-time
        (
            "2026-10-12T09:30:00Z",
            {"date:2026-10-12", "md:10-12", "2026", "time:09:30"},
        ),
        # times
        ("16:00", {"time:16:00"}),
        ("02:00", {"time:02:00"}),
        ("9:30", {"time:09:30"}),
        # a bare year is a plain number
        ("2026", {"2026"}),
        # seed corpus lines
        (
            "Saturday 17 October, 02:00 to 04:00 SGT",
            {"md:10-17", "time:02:00", "time:04:00"},
        ),
        (
            "Q3 2026 revenue: SGD 48.6 million, up 18% year on year (Q3 2025: SGD 41.2 million).",
            {"18%", "2025", "2026", "41200000", "48600000"},
        ),
        ("- **Q3 2026 revenue: SGD 48.6 million**, up **18%", {"2026", "48600000", "18%"}),
    ],
)
def test_extraction_table(text: str, keys: set[str]) -> None:
    assert numeric_facts(text) == frozenset(keys)


@pytest.mark.parametrize(
    "text",
    ["E1", "[E3]", "v2", "FY2026", "Q3", "1.2.3", "10x", "SGD10,000", "1,00,000", "3,5"],
)
def test_labels_and_versions_are_not_facts(text: str) -> None:
    assert numeric_facts(text) == frozenset()


@pytest.mark.parametrize(
    "text",
    ["2026-13-01", "2026-02-31", "32 October", "0 October", "30 Feb", "25:00", "12:61"],
)
def test_invalid_dates_and_times_yield_nothing(text: str) -> None:
    assert numeric_facts(text) == frozenset()


def test_invalid_time_in_an_iso_timestamp_keeps_only_the_date() -> None:
    assert numeric_facts("2026-10-01T25:00") == OCT_1_2026
    assert numeric_facts("2026-02-31T10:00") == frozenset()


def test_leap_day_needs_a_leap_year() -> None:
    assert numeric_facts("29 Feb 2024") == {"date:2024-02-29", "md:2-29", "2024"}
    assert numeric_facts("29 Feb 2026") == frozenset()
    assert numeric_facts("29 Feb") == {"md:2-29"}


def test_times_and_iso_dates_are_not_split() -> None:
    assert numeric_facts("16:00") == {"time:16:00"}
    assert numeric_facts("16:00:00") == {"time:16:00"}
    keys = numeric_facts("Cutover starts 2026-10-01 at 16:00.")
    assert keys == OCT_1_2026 | {"time:16:00"}
    assert not {"10", "1", "01", "16", "0", "00"} & keys


@pytest.mark.parametrize(
    ("variants", "key"),
    [
        (["10,000", "10000", "10k", "10K", "10 thousand", "10.0k"], "10000"),
        (["1.5 million", "1.5M", "1.5m", "1.5 mm", "1.5mn", "1.5 mil", "1,500,000"], "1500000"),
        (["3 billion", "3bn", "3B", "3,000,000,000", "3000 million"], "3000000000"),
        (["2.50", "2.5", "2.500"], "2.5"),
        (["18%", "18 percent", "18.0%"], "18%"),
    ],
)
def test_scaled_equivalence(variants: list[str], key: str) -> None:
    for variant in variants:
        assert numeric_facts(variant) == {key}, variant


def test_values_render_exactly_without_exponent() -> None:
    assert numeric_facts("SGD 999,999,999,999 billion") == {"999999999999000000000"}
    assert numeric_facts("SGD 10,000.50") == {"10000.5"}
    # Beyond the default 28-digit Decimal context: distinct values stay distinct.
    long_a = "12345678901234567890123456789012345"
    long_b = "12345678901234567890123456789012344"
    assert numeric_facts(long_a) == {long_a}
    assert numeric_facts(long_b) == {long_b}


def test_documented_limits() -> None:
    assert numeric_facts("one million") == frozenset()  # word numbers are not parsed
    assert numeric_facts("SGD 50 to 52 million") == {"50", "52000000"}  # ranges not expanded
    assert numeric_facts("01/10/2026") == {"1", "10", "2026"}  # slash dates are plain numbers
    assert numeric_facts("October 2026") == {"2026"}  # month-year yields only the year
    assert numeric_facts("10 may apply") == {"md:5-10"}  # day + month-word reads as a date


# ---------------------------------------------------------------------------- support check


def test_wrong_value_is_unsupported() -> None:
    evidence = "Payments above SGD 10,000 require CFO approval."
    assert unsupported_numeric_facts("Payments above SGD 20,000 need the CFO.", evidence) == {
        "20000"
    }
    assert unsupported_numeric_facts("Revenue grew 21%.", "Revenue grew 18%.") == {"21%"}
    assert unsupported_numeric_facts("Cutover on 18 October.", "Cutover on 17 October.") == {
        "md:10-18"
    }
    assert unsupported_numeric_facts("Cutover at 03:00.", "Cutover at 02:00.") == {"time:03:00"}


def test_claim_facts_must_be_a_subset_of_evidence_facts() -> None:
    evidence = "Saturday 17 October, 02:00 to 04:00 SGT. Budget SGD 1.2 million."
    assert unsupported_numeric_facts("The cutover is on 17 October at 02:00.", evidence) == set()
    assert unsupported_numeric_facts("A SGD 1,200,000 budget.", evidence) == set()
    assert unsupported_numeric_facts("17 October at 02:00 for SGD 2 million.", evidence) == {
        "2000000"
    }
    # A year-less claim date is supported by the dated evidence, not the other way round.
    assert unsupported_numeric_facts("On 17 October.", "On 17 October 2026.") == set()
    assert unsupported_numeric_facts("On 17 October 2026.", "On 17 October.") == {
        "date:2026-10-17",
        "2026",
    }


def test_scaled_claim_matches_evidence() -> None:
    evidence = "Payments above SGD 10,000 require CFO approval."
    assert unsupported_numeric_facts("Payments above SGD 10k require CFO approval.", evidence) == (
        set()
    )


def test_verbatim_claim_is_never_unsupported() -> None:
    evidence = "Payments above SGD 10,000,000\n need board approval."
    # Key-wise the claim says 10000 and the evidence 10000000, but the claim is verbatim text.
    assert numeric_facts("Payments above SGD 10,000") == {"10000"}
    assert unsupported_numeric_facts("Payments above SGD 10,000", evidence) == set()
    assert unsupported_numeric_facts("PAYMENTS   above sgd 10,000", evidence) == set()


def test_claim_without_numbers_is_never_unsupported() -> None:
    assert unsupported_numeric_facts("CFO approval is required.", "Revenue grew 18%.") == set()
    assert unsupported_numeric_facts("Board approval is needed.", "") == set()


def test_word_number_evidence_does_not_confirm_digits() -> None:
    claim = "The CFO limit is SGD 1 million."
    assert unsupported_numeric_facts(claim, "The CFO limit is SGD one million.") == {"1000000"}


def test_extraction_is_deterministic() -> None:
    text = "Q3 2026 revenue: SGD 48.6 million, up 18% (Q3 2025: SGD 41.2 million) on 1 Oct at 9:30."
    first = numeric_facts(text)
    assert isinstance(first, frozenset)
    assert all(numeric_facts(text) == first for _ in range(5))
    assert unsupported_numeric_facts("SGD 50 million", text) == {"50000000"}
    assert unsupported_numeric_facts("SGD 50 million", text) == {"50000000"}
