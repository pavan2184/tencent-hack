"""Deterministic numeric and date facts for the lexical verifier (no model, stdlib only).

Borrowed from GBrain's query-time check (``synthesize-verify.ts``: ``numericFacts`` /
``unsupportedNumericClaims``): every number, percentage, date and time in a text becomes a
canonical key, and a claim is numerically supported only when every key it mentions also occurs
in the cited evidence text (or the claim occurs verbatim in it).

Keys:

* numbers: the plain decimal value with scale words applied and no trailing zeros
  (``10,000`` / ``10k`` / ``10 thousand`` -> ``10000``; ``SGD 2.5 million`` -> ``2500000``);
* percentages: the value plus ``%`` (``18 percent`` -> ``18%``);
* dates: ``date:YYYY-MM-DD`` and the year when a year is given, plus ``md:M-D`` always
  (``1 October 2026`` / ``Oct 1st, 2026`` / ``2026-10-01``);
* times: ``time:HH:MM`` (``16:00``; an ISO date-time also yields its time).

Labels are not facts: a number glued to a word character, a dot or a broken comma group
(``E1``, ``[E3]``, ``FY2026``, ``Q3``, ``v2``, ``1.2.3``, ``10x``, ``SGD10,000``) yields nothing,
and invalid dates and times (``2026-02-31``, ``25:00``) yield nothing.

Documented limits: word numbers (``one million``) are not parsed (conservative: a digit claim
against word-number evidence is demoted; a word-number claim is not checked); ranges are not
expanded; slash dates (``01/10/2026``) are plain numbers; a month-year (``October 2026``) yields
only the year; ``am``/``pm`` is not read; a day-number before a month-word is read as a date
(``10 may apply`` -> ``md:5-10``), which is symmetric between claim and evidence.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Context, Decimal

_MONTH_NUMBER: dict[str, int] = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_ORDINAL = r"(?:st|nd|rd|th)?"
_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_SCALE_EXPONENT: dict[str, int] = {
    "k": 3,
    "thousand": 3,
    "m": 6,
    "mm": 6,
    "mn": 6,
    "mil": 6,
    "million": 6,
    "b": 9,
    "bn": 9,
    "billion": 9,
}

# Alternatives are tried in this order and each match consumes its span exactly once, so an
# ISO date never leaks "10" and "01", and "16:00" never leaks "16" and "00". A number never
# starts or ends inside a comma group, so "SGD10,000" cannot leak "000".
_FACT_RE = re.compile(
    rf"""
    (?P<iso>(?<!\d)(?P<iso_y>\d{{4}})-(?P<iso_m>\d{{2}})-(?P<iso_d>\d{{2}})
        (?:[T ](?P<iso_h>\d{{2}}):(?P<iso_min>\d{{2}})(?::\d{{2}}(?:\.\d+)?)?
           (?:Z|[+-]\d{{2}}:?\d{{2}})?)?(?!\d))
  | (?P<time>(?<![\w:])(?P<t_h>\d{{1,2}}):(?P<t_m>\d{{2}})(?::\d{{2}})?(?![\w:]))
  | (?P<dmy>\b(?P<dmy_d>\d{{1,2}}){_ORDINAL}\s+(?:of\s+)?(?P<dmy_mon>{_MONTH})\b\.?
        (?:,?\s+(?P<dmy_y>\d{{4}})\b)?)
  | (?P<mdy>\b(?P<mdy_mon>{_MONTH})\b\.?\s+(?P<mdy_d>\d{{1,2}}){_ORDINAL}\b
        (?:,?\s+(?P<mdy_y>\d{{4}})\b)?)
  | (?P<num>(?<![\w.])(?<!\d,)(?P<n_int>\d{{1,3}}(?:,\d{{3}})+|\d+)(?P<n_frac>\.\d+)?
        (?:\s*(?P<n_unit>%|percent|thousand|million|billion|mil|bn|mm|mn|k|m|b))?(?!\w|[.,]\d))
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _plain(number: str, exponent: int = 0) -> str:
    """``2.50`` -> ``2.5``, ``2.5`` scaled by 6 -> ``2500000``: exact, no exponent, no trailing
    zeros. Built from the string with a context as wide as the digits, so huge values never
    round (the default 28-digit context would merge distinct values)."""
    value = Decimal(f"{number}E{exponent}")
    exact = Context(prec=max(1, len(value.as_tuple().digits)))
    return format(value.normalize(exact), "f")


def _date_keys(year: int | None, month: int, day: int) -> set[str]:
    """``md:M-D`` (+ ``date:YYYY-MM-DD`` and the year when given); nothing for an invalid date."""
    if not (1 <= month <= 12 and 1 <= day <= _DAYS_IN_MONTH[month - 1]):
        return set()
    if year is None:
        return {f"md:{month}-{day}"}
    try:
        date(year, month, day)
    except ValueError:
        return set()
    return {f"md:{month}-{day}", f"date:{year:04d}-{month:02d}-{day:02d}", str(year)}


def _time_keys(hour: int, minute: int) -> set[str]:
    """``time:HH:MM``; nothing for an invalid time."""
    if hour > 23 or minute > 59:
        return set()
    return {f"time:{hour:02d}:{minute:02d}"}


def numeric_facts(text: str) -> frozenset[str]:
    """Canonical keys of every number, percentage, date and time mentioned in ``text``."""
    keys: set[str] = set()
    for match in _FACT_RE.finditer(text):
        if match.group("iso"):
            day_keys = _date_keys(int(match["iso_y"]), int(match["iso_m"]), int(match["iso_d"]))
            keys |= day_keys
            if day_keys and match["iso_h"] is not None:
                keys |= _time_keys(int(match["iso_h"]), int(match["iso_min"]))
        elif match.group("time"):
            keys |= _time_keys(int(match["t_h"]), int(match["t_m"]))
        elif match.group("dmy"):
            year = int(match["dmy_y"]) if match["dmy_y"] else None
            keys |= _date_keys(year, _MONTH_NUMBER[match["dmy_mon"].lower()], int(match["dmy_d"]))
        elif match.group("mdy"):
            year = int(match["mdy_y"]) if match["mdy_y"] else None
            keys |= _date_keys(year, _MONTH_NUMBER[match["mdy_mon"].lower()], int(match["mdy_d"]))
        else:
            number = match["n_int"].replace(",", "") + (match["n_frac"] or "")
            unit = (match["n_unit"] or "").lower()
            if unit in ("%", "percent"):
                keys.add(_plain(number) + "%")
            else:
                keys.add(_plain(number, _SCALE_EXPONENT.get(unit, 0)))
    return frozenset(keys)


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def unsupported_numeric_facts(claim: str, evidence_text: str) -> frozenset[str]:
    """Keys mentioned by ``claim`` that ``evidence_text`` does not mention.

    Empty when the claim has no numeric facts or occurs verbatim (case- and whitespace-
    insensitive) in the evidence, so extractive claims never pay for the extraction.
    """
    claim_keys = numeric_facts(claim)
    if not claim_keys or _normalized(claim) in _normalized(evidence_text):
        return frozenset()
    return claim_keys - numeric_facts(evidence_text)
