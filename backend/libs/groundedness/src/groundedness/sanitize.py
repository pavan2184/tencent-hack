"""Prompt-injection screening for retrieved evidence (regex stub).

``RegexInjectionSanitizer`` runs a table of named patterns over every evidence title and body:

* any **high** severity match quarantines the span: ``quarantined=True``, text left intact, and
  composers/verifiers must never show it to a model or cite it;
* **low/medium** matches are cut out of the text and ``was_modified=True``;
* clean text is returned byte-identical.

Matching runs on a copy of the text with zero-width characters removed (offsets are mapped back to
the original), so ``ig\\u200bnore previous instructions`` is still caught. This is a deterministic
floor, not a classifier: the injection corpus and evals are on Raphael's list (see README).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from groundedness.models import (
    EvidenceSpan,
    InjectionFlag,
    InjectionSeverity,
    SanitizedEvidence,
)

_FLAGS = re.IGNORECASE | re.MULTILINE
_ZERO_WIDTH = "​‌‍﻿"
_ZERO_WIDTH_RE = re.compile(f"[{_ZERO_WIDTH}]+")
TITLE_SUFFIX = "@title"


@dataclass(frozen=True, slots=True)
class InjectionPattern:
    """One named detection rule.

    ``requires``: the match only counts if this sub-pattern also occurs inside it (used for HTML
    comments, which are only suspicious when they carry instruction words).
    ``raw``: match against the raw text instead of the zero-width-stripped view.
    """

    id: str
    severity: InjectionSeverity
    regex: re.Pattern[str]
    description: str
    requires: re.Pattern[str] | None = None
    raw: bool = False


_HIGH = InjectionSeverity.HIGH
_MEDIUM = InjectionSeverity.MEDIUM
_LOW = InjectionSeverity.LOW

DEFAULT_PATTERNS: tuple[InjectionPattern, ...] = (
    InjectionPattern(
        id="ignore_instructions",
        severity=_HIGH,
        regex=re.compile(
            r"\b(?:ignore|forget|override)\s+(?:(?:all|any|the|your)\s+)*"
            r"(?:previous|prior|above|earlier|preceding|system)\s+"
            r"(?:instructions?|prompts?|rules|directions|guidelines|context)\b",
            _FLAGS,
        ),
        description="Tells the model to drop its instructions.",
    ),
    InjectionPattern(
        id="disregard_above",
        severity=_HIGH,
        regex=re.compile(
            r"\bdisregard\s+(?:(?:all|any|the)\s+)*"
            r"(?:above|previous|prior|preceding|earlier|foregoing)\b"
            r"(?:\s+(?:instructions?|text|messages?|rules|context))?",
            _FLAGS,
        ),
        description="Tells the model to disregard earlier content.",
    ),
    InjectionPattern(
        id="you_are_now",
        severity=_MEDIUM,
        regex=re.compile(
            r"\byou\s+are\s+now\b(?:\s+(?:an?|in|acting\s+as|no\s+longer|free|unrestricted|"
            r"jailbroken|dan)\b)?",
            _FLAGS,
        ),
        description="Persona or mode override.",
    ),
    InjectionPattern(
        id="new_instructions",
        severity=_HIGH,
        regex=re.compile(
            r"\b(?:new|updated|revised|additional)\s+(?:system\s+)?instructions?\s*:", _FLAGS
        ),
        description="Injects a replacement instruction block.",
    ),
    InjectionPattern(
        id="reveal_system_prompt",
        severity=_HIGH,
        regex=re.compile(
            r"\b(?:reveal|print|show|repeat|output|leak|display|dump)\s+(?:me\s+)?(?:your|the)\s+"
            r"(?:system\s+prompt|hidden\s+prompt|initial\s+instructions|instructions)\b",
            _FLAGS,
        ),
        description="Asks the model to disclose its instructions.",
    ),
    InjectionPattern(
        id="system_prompt_mention",
        severity=_LOW,
        regex=re.compile(r"\bsystem\s+prompt\b", _FLAGS),
        description="Mentions the system prompt.",
    ),
    InjectionPattern(
        id="role_spoofing",
        severity=_MEDIUM,
        regex=re.compile(r"^[ \t]*(?:system|assistant|user)[ \t]*:[ \t]*", _FLAGS),
        description="A line that impersonates a chat role; the role label is removed.",
    ),
    InjectionPattern(
        id="chat_template_tokens",
        severity=_HIGH,
        regex=re.compile(
            r"<\|(?:im_start|im_end|im_sep|endoftext|system|user|assistant)\|>"
            r"|\[/?INST\]|<</?SYS>>",
            _FLAGS,
        ),
        description="Raw chat-template control tokens.",
    ),
    InjectionPattern(
        id="markdown_hidden_comment",
        severity=_MEDIUM,
        regex=re.compile(r"^[ \t]*\[(?://|comment)\]:[ \t]*(?:#|<>).*$", _FLAGS),
        description="Markdown comment line that renders invisibly.",
    ),
    InjectionPattern(
        id="html_comment_instruction",
        severity=_HIGH,
        regex=re.compile(r"<!--.*?-->", _FLAGS | re.DOTALL),
        requires=re.compile(
            r"\b(?:ignore|disregard|instructions?|assistant|system|prompt|you\s+are|you\s+must|"
            r"do\s+not|respond|reply|answer)\b",
            _FLAGS,
        ),
        description="Hidden HTML comment carrying instruction words.",
    ),
    InjectionPattern(
        id="zero_width_chars",
        severity=_LOW,
        regex=_ZERO_WIDTH_RE,
        description="Zero-width characters (U+200B-U+200D, U+FEFF), used to hide text.",
        raw=True,
    ),
    InjectionPattern(
        id="conceal_from_user",
        severity=_HIGH,
        regex=re.compile(
            r"\b(?:do\s+not|don['’]t|never)\s+(?:tell|inform|show|alert|notify|"
            r"mention\s+(?:this\s+)?to)\s+the\s+(?:user|employee|asker|human)\b",
            _FLAGS,
        ),
        description="Asks the model to hide something from the user.",
    ),
    InjectionPattern(
        id="exfiltration",
        severity=_HIGH,
        regex=re.compile(
            r"\bexfiltrat\w*|\bsend\b[^\n]{0,200}?\bto\s+https?://\S+",
            _FLAGS,
        ),
        description="Asks the model to move data to an external location.",
    ),
)


def _strip_zero_width(text: str) -> tuple[str, list[int]]:
    """Return ``text`` without zero-width chars plus a map: normalized index -> original index."""
    kept: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(text):
        if char not in _ZERO_WIDTH:
            kept.append(char)
            index_map.append(index)
    return "".join(kept), index_map


def scan(
    text: str,
    patterns: Iterable[InjectionPattern] = DEFAULT_PATTERNS,
    *,
    suffix: str = "",
) -> list[InjectionFlag]:
    """Every pattern match in ``text``, sorted by ``(start, end, pattern_id)``.

    Offsets index into ``text`` itself; ``suffix`` is appended to each ``pattern_id``.
    """
    normalized, index_map = _strip_zero_width(text)
    flags: list[InjectionFlag] = []
    for pattern in patterns:
        haystack = text if pattern.raw else normalized
        for match in pattern.regex.finditer(haystack):
            if match.end() <= match.start():
                continue
            if pattern.requires is not None and not pattern.requires.search(match.group()):
                continue
            if pattern.raw:
                start, end = match.start(), match.end()
            else:
                start, end = index_map[match.start()], index_map[match.end() - 1] + 1
            flags.append(
                InjectionFlag(
                    pattern_id=pattern.id + suffix,
                    matched_text=text[start:end],
                    start=start,
                    end=end,
                    severity=pattern.severity,
                )
            )
    flags.sort(key=lambda flag: (flag.start, flag.end, flag.pattern_id))
    return flags


def remove_spans(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Cut ``[start, end)`` spans out of ``text`` (overlaps merged).

    Where a cut leaves a space on both sides, one of them is dropped so no double space appears.
    """
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    pieces: list[str] = []
    cursor = 0
    last_char = ""
    for start, end in merged:
        kept = text[cursor:start]
        if kept:
            pieces.append(kept)
            last_char = kept[-1]
        cursor = end
        if last_char in (" ", "\t") and text[cursor : cursor + 1] in (" ", "\t"):
            cursor += 1
    pieces.append(text[cursor:])
    return "".join(pieces)


class RegexInjectionSanitizer:
    """Deterministic, regex-based ``EvidenceSanitizer``. See the module docstring."""

    def __init__(self, patterns: Sequence[InjectionPattern] = DEFAULT_PATTERNS) -> None:
        ids = [pattern.id for pattern in patterns]
        if len(set(ids)) != len(ids):
            raise ValueError("injection pattern ids must be unique")
        self.patterns: tuple[InjectionPattern, ...] = tuple(patterns)

    def sanitize(self, evidence: Sequence[EvidenceSpan]) -> list[SanitizedEvidence]:
        return [self.sanitize_one(span) for span in evidence]

    def sanitize_one(self, span: EvidenceSpan) -> SanitizedEvidence:
        body_flags = scan(span.text, self.patterns)
        title_flags = scan(span.title, self.patterns, suffix=TITLE_SUFFIX)
        flags = body_flags + title_flags
        if any(flag.severity is InjectionSeverity.HIGH for flag in flags):
            return SanitizedEvidence(evidence=span, flags=flags, quarantined=True)
        if not flags:
            return SanitizedEvidence(evidence=span)
        cleaned = span.model_copy(
            update={
                "text": remove_spans(span.text, ((f.start, f.end) for f in body_flags)),
                "title": remove_spans(span.title, ((f.start, f.end) for f in title_flags)),
            }
        )
        return SanitizedEvidence(evidence=cleaned, flags=flags, was_modified=True)
