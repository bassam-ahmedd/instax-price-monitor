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
    "sqr": "square",
    "org": "orange", "bl": "blue", "wht": "white", "bk": "black",
    "grn": "green", "pnk": "pink", "gry": "gray", "bg": "beige", "br": "brown",
    "frm": "frame", "hrt": "heart", "sktch": "sketch", "lavndr": "lavender",
    "rnbw": "rainbow", "lemnd": "lemonade", "spr": "spray", "gltr": "glitter",
    "met": "metallic", "snst": "sunset", "contetti": "confetti",
    "brush": "brushed", "str": "star", "illm": "illumi",
    "contact": "contact sheet", "macaron": "macron", "rose": "pink",
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
    # "SQ" standing alone means "Square" (the product line, as our sheet
    # uses it in "INSTAX SQ LINK WHT"). "SQ" directly followed by a digit
    # (SQ1, SQ6, SQ40) is a specific model code, not our line-name
    # abbreviation - expanding it too would make an unrelated "SQ6"
    # accessory falsely appear to share our "Square" line.
    text = re.sub(r"\bsq(?!\d)\b", "square", text.lower())
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
    if re.search(r"\btp\s?link\b", t):
        return None  # TP-Link brand name, not an Instax printer
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


GENERIC_WORDS = {"instax", "fuji", "film", "camera", "printer", "plus"}


def _content_words(text: str) -> set:
    """Every meaningful, non-generic word in the text (product line like
    'mini'/'square', sub-model like 'evo'/'liplay', pattern name like
    'rainbow'/'confetti') - excluding brand/category boilerplate, colors
    (gated separately), and digits (gated separately).

    Used as a hard gate: ALL of the query's content words must appear in
    the candidate. This is what actually stops false matches within a
    small catalog, where *something* will always have the highest fuzzy
    score even if it's completely wrong - e.g. 'Square Link White' matching
    an unrelated 'SQ6 Camera Frame Borders' accessory just because both
    share the word 'white', or 'Mini Rainbow' matching 'Square Rainbow'
    because 'rainbow' overlaps but the product line doesn't.
    """
    tokens = _tokens(text)
    digit_like = {t for t in tokens if t.isdigit()}
    return tokens - GENERIC_WORDS - COLOR_WORDS - digit_like


COLOR_WORDS = {
    "white", "black", "blue", "green", "pink", "purple", "orange",
    "beige", "brown", "gray", "grey", "gold", "silver", "red", "yellow",
}


def _color_words(text: str) -> set:
    """Explicit color names in the text. Gated like digits/model-words:
    if the query names a color, the candidate must share it - otherwise a
    'Sand Beige' item could match the only same-family product in stock
    even when it's actually 'Misty White'."""
    normalized = _normalize(text)
    return {w for w in COLOR_WORDS if re.search(rf"\b{w}\b", normalized)}


def _digit_runs(text: str) -> set:
    """All numeric runs in the text. Used to stop 'SQ1' from matching
    'SQ40' just because they share every other word."""
    return set(re.findall(r"\d+", _normalize(text)))


def similarity(a: str, b: str) -> float:
    """
    Combined score: how much of the QUERY's content is covered by the
    candidate (not symmetric overlap - our queries are short abbreviations
    while retailer titles are verbose marketing copy, e.g. "FUJIFILM INSTAX
    Mini Evo Hybrid Instant Film Camera, 28mm lens, 3 inch Screen, Brown"
    for a query of just "instax mini evo brown"; penalizing the candidate
    for its extra words would unfairly sink an otherwise perfect match),
    weighted with sequence ratio for structural sanity-checking.
    Returns 0..1, higher is better.
    """
    a_norm, b_norm = _normalize(a), _normalize(b)
    seq_ratio = SequenceMatcher(None, a_norm, b_norm).ratio()

    a_tok, b_tok = _tokens(a), _tokens(b)
    if not a_tok or not b_tok:
        coverage = 0.0
    else:
        coverage = len(a_tok & b_tok) / len(a_tok)

    return 0.4 * seq_ratio + 0.6 * coverage


def _is_fuji_branded(text: str) -> bool:
    """Every real target product is Fujifilm/Instax branded. Rejecting
    anything else outright is a much more robust safety net than trying to
    patch category inference for every possible brand collision (TP-Link
    routers, Canon/Epson/Brother printers, Honor phones, etc. all contain
    words like 'link' or 'printer' that would otherwise slip past the
    category gate)."""
    return bool(re.search(r"\b(fuji|fujifilm|instax)\b", _normalize(text)))


def best_match(query: str, candidates: list, key=lambda c: c, threshold: float = 0.45):
    """
    candidates: list of items (or dicts) to score against `query`.
    key: function extracting the title string from a candidate.
    Returns (candidate, score) for the best candidate if its score >=
    threshold, else (None, best_score_seen). Candidates that aren't
    Fuji/Instax branded, or whose inferred category (camera/film/printer),
    model-number digits, or specific model word conflict with the query's,
    are excluded outright regardless of text score.
    """
    query_category = infer_category(query)
    query_digits = _digit_runs(query)
    query_content = _content_words(query)
    query_colors = _color_words(query)

    best = None
    best_score = 0.0
    for c in candidates:
        title = key(c)
        if not title:
            continue

        if not _is_fuji_branded(title):
            continue

        if query_category:
            cand_category = infer_category(title)
            if cand_category and cand_category != query_category:
                continue

        if query_digits:
            cand_digits = _digit_runs(title)
            if query_digits.isdisjoint(cand_digits):
                continue

        if query_content:
            cand_tokens = _tokens(title)
            if not query_content.issubset(cand_tokens):
                continue

        if query_colors:
            cand_colors = _color_words(title)
            if query_colors.isdisjoint(cand_colors):
                continue

        score = similarity(query, title)
        if score > best_score:
            best_score = score
            best = c

    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score
