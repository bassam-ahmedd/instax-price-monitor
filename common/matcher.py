"""
Fuzzy matching between our item descriptions (e.g. from the sourcing sheet)
and product titles found on Extra / Jarir search results.
"""
import re
from difflib import SequenceMatcher

STOPWORDS = {"fujifilm", "single", "pack", "twin", "the", "and", "instant"}


def infer_category(text: str) -> str | None:
    """
    Coarse product-type from a title/description: camera, film, or printer.
    Used as a hard gate so a film pack never gets matched to a camera (or
    vice versa) just because the fuzzy text score happens to be high -
    "Film" and "Mini 12" both appear in a camera's title.

    Uses word boundaries: naive substring checks would match "film" inside
    the brand name "Fujifilm" itself and mis-tag every product as film.
    """
    t = text.lower()
    if re.search(r"\bcamera\b", t):
        return "camera"
    if re.search(r"\bfilm\b", t):
        return "film"
    if re.search(r"\b(printer|link)\b", t):
        return "printer"
    return None


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t]
    return " ".join(tokens)


def _tokens(text: str) -> set:
    return {t for t in _normalize(text).split() if t not in STOPWORDS}


SEARCH_NOISE_WORDS = {"single", "twin", "pack"}


def clean_query(text: str) -> str:
    """
    Strip words that hurt search-engine relevance without helping our own
    matching (e.g. 'SINGLE PACK' / 'TWIN PACK' derails Extra's Unbxd search
    toward unrelated 'single door fridge' results). Used only for building
    the outgoing search query - the strict category/model gates above still
    run against the full original item text.
    """
    normalized = _normalize(text)
    tokens = [t for t in normalized.split() if t not in SEARCH_NOISE_WORDS]
    return " ".join(tokens)


def _digit_runs(text: str) -> set:
    """All numeric runs in the text, spacing-agnostic (so 'Mini12' and
    'Mini 12' both yield {'12'}). Used to stop 'SQ1' from matching 'SQ40'
    just because they share every other word."""
    return set(re.findall(r"\d+", _normalize(text)))


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


def best_match(query: str, candidates: list, key=lambda c: c, threshold: float = 0.5):
    """
    candidates: list of items (or dicts) to score against `query`.
    key: function extracting the title string from a candidate.
    Returns the best candidate if its score >= threshold, else None.
    Candidates whose inferred category (camera/film/printer) conflicts
    with the query's are excluded outright, regardless of text score.
    """
    query_category = infer_category(query)
    query_digits = _digit_runs(query)

    best = None
    best_score = 0.0
    for c in candidates:
        title = key(c)
        if not title:
            continue

        if query_category:
            cand_category = infer_category(title)
            if cand_category and cand_category != query_category:
                continue

        if query_digits:
            cand_digits = _digit_runs(title)
            if cand_digits and query_digits.isdisjoint(cand_digits):
                continue

        score = similarity(query, title)
        if score > best_score:
            best_score = score
            best = c

    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score
