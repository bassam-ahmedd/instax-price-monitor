"""
Fuzzy matching between our item descriptions (e.g. from the sourcing sheet)
and product titles found on Extra / Jarir search results.
"""
import re
from difflib import SequenceMatcher

STOPWORDS = {"fujifilm", "camera", "printer", "single", "pack", "twin", "the", "and"}


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t]
    return " ".join(tokens)


def _tokens(text: str) -> set:
    return {t for t in _normalize(text).split() if t not in STOPWORDS}


def similarity(a: str, b: str) -> float:
    """
    Combined score: token-overlap (Jaccard) weighted with sequence ratio.
    Returns 0..1, higher is better.
    """
    a_norm, b_norm = _normalize(a), _normalize(b)
    seq_ratio = SequenceMatcher(None, a_norm, b_norm).ratio()

    a_tok, b_tok = _tokens(a), _tokens(b)
    if not a_tok or not b_tok:
        jaccard = 0.0
    else:
        jaccard = len(a_tok & b_tok) / len(a_tok | b_tok)

    return 0.5 * seq_ratio + 0.5 * jaccard


def best_match(query: str, candidates: list, key=lambda c: c, threshold: float = 0.45):
    """
    candidates: list of items (or dicts) to score against `query`.
    key: function extracting the title string from a candidate.
    Returns the best candidate if its score >= threshold, else None.
    """
    best = None
    best_score = 0.0
    for c in candidates:
        title = key(c)
        if not title:
            continue
        score = similarity(query, title)
        if score > best_score:
            best_score = score
            best = c

    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score
