"""
Fuzzy matching between our item codes (the sourcing sheet uses heavily
abbreviated codes like "INSTAX SQR SQ1 ORG" / "MINI HRT SKTCH-SINGLE FILM")
and full product titles found on Extra / Jarir search results.
"""
import re
from difflib import SequenceMatcher

STOPWORDS = {"fujifilm", "single", "pack", "twin", "the", "and", "instant"}

# The sourcing sheet abbreviates colors, materials, and pattern names.
# Confirmed against the full descriptions in the original sourcing file
# (e.g. "ORG" <-> "Terracotta Orange", "BL" <-> "Blue", "BK" <-> "Black").
ABBREVIATIONS = {
    "sqr": "square", "sq": "square",
    "org": "orange", "bl": "blue", "wht": "white", "bk": "black",
    "grn": "green", "pnk": "pink", "gry": "gray", "bg": "beige", "br": "brown",
    "frm": "frame", "hrt": "heart", "sktch": "sketch", "lavndr": "lavender",
    "rnbw": "rainbow", "lemnd": "lemonade", "spr": "spray", "gltr": "glitter",
    "met": "metallic", "snst": "sunset", "contetti": "confetti",
    "brush": "brushed", "str": "star", "illm": "illumi",
    "contact": "contact sheet",
}


def _split_alnum(text: str) -> list:
    """Lowercase, insert spaces at letter/digit boundaries (so 'Mini12' and
    'Link3' tokenize the same as 'Mini 12' / 'Link 3' in real product
    titles), strip punctuation, and split into raw tokens."""
    text = text.lower()
    text = re.sub(r"(?<=[a-z])(?=[0-9])", " ", text)
    text = re.sub(r"(?<=[0-9])(?=[a-z])", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return [t for t in text.split() if t]


def _normalize(text: str) -> str:
    """Tokenize and expand abbreviated codes to full words."""
    tokens = [ABBREVIATIONS.get(t, t) for t in _split_alnum(text)]
    return " ".join(tokens)


def infer_category(text: str) -> str | None:
    """
    Coarse product-type from a title/description: camera, film, or printer.
    Used as a hard gate so a film pack never gets matched to a camera (or
    vice versa) just because the fuzzy text score happens to be high.

    Runs on the normalized/expanded text and uses word boundaries: a naive
    substring check would match "film" inside the brand name "Fujifilm"
    itself and mis-tag every product as film.
    """
    t = _normalize(text)
    if re.search(r"\bcamera\b", t):
        return "camera"
    if re.search(r"\bfilm\b", t):
        return "film"
    if re.search(r"\b(printer|link)\b", t):
        return "printer"
    return None


def _tokens(text: str) -> set:
    return {t for t in _normalize(text).split() if t not in STOPWORDS}


SEARCH_NOISE_WORDS = {"single", "twin", "pack"}


def clean_query(text: str) -> str:
    """
    Build an outgoing search-engine query: expand abbreviations (so the
    search engine actually sees "square", "orange", etc.) and drop words
    that hurt relevance without helping matching (e.g. 'SINGLE PACK'
    derails Extra's Unbxd search toward unrelated 'single door fridge'
    results). The strict category/model gates below still run against the
    full original item text, not this cleaned version.
    """
    tokens = [t for t in _normalize(text).split() if t not in SEARCH_NOISE_WORDS]
    return " ".join(tokens)


SPECIFIC_MODEL_WORDS = {"evo", "liplay", "pal", "cinema"}


def _specific_model_words(text: str) -> set:
    """Sub-model identifiers that name a distinct product line (LiPlay,
    Evo, Pal, Cinema) rather than a generic descriptor. Unlike common words
    ('mini', 'wide') these are rare enough that requiring an exact match
    stops e.g. 'Mini LiPlay Plus' from matching a plain 'Mini 12' just
    because they share every other word."""
    normalized = _normalize(text)
    return {w for w in SPECIFIC_MODEL_WORDS if re.search(rf"\b{w}\b", normalized)}


def _digit_runs(text: str) -> set:
    """All numeric runs in the text. Used to stop 'SQ1' from matching
    'SQ40' just because they share every other word."""
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


def best_match(query: str, candidates: list, key=lambda c: c, threshold: float = 0.42):
    """
    candidates: list of items (or dicts) to score against `query`.
    key: function extracting the title string from a candidate.
    Returns (candidate, score) for the best candidate if its score >=
    threshold, else (None, best_score_seen). Candidates whose inferred
    category (camera/film/printer) or model-number digits conflict with
    the query's are excluded outright, regardless of text score.
    """
    query_category = infer_category(query)
    query_digits = _digit_runs(query)
    query_model_words = _specific_model_words(query)

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

        if query_model_words:
            cand_model_words = _specific_model_words(title)
            if not (query_model_words & cand_model_words):
                continue

        score = similarity(query, title)
        if score > best_score:
            best_score = score
            best = c

    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score
