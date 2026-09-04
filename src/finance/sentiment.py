"""NLP sentiment scoring for financial news and analyst actions.

Produces a bullish/bearish score from headlines, analyst upgrades/downgrades,
and insider activity. Rules-based lexicon scoring (no external NLP dependency)
that is deterministic and testable offline.
"""

import re

BULLISH_TERMS = [
    "beat", "beats", "upgrade", "upgraded", "buy", "outperform", "strong buy",
    "raise", "raised", "positive", "growth", "record", "rally",
    "gain", "gains", "bullish", "accumulate", "overweight", "insider buy",
    "institutional", "boost", "boosted", "milestone",
]

BEARISH_TERMS = [
    "miss", "misses", "downgrade", "downgraded", "sell", "underperform",
    "cut", "negative", "decline", "drop", "falls", "plunge",
    "loss", "losses", "bearish", "reduce", "underweight", "insider sell",
    "lawsuit", "investigation", "fraud", "weak", "warning", "layoff",
]

NEGATION_WORDS = {"not", "no", "won't", "wont", "without", "never", "denies", "deny"}


def _tokenize(text: str) -> list:
    return re.findall(r"[a-z']+", text.lower())


def _score_window(tokens: list, target_index: int) -> int:
    """Score a single target token considering a small negation window."""
    window = tokens[max(0, target_index - 3): target_index + 2]
    negated = any(w in NEGATION_WORDS for w in window)
    value = 1 if not negated else -1
    return value


def _count_terms(tokens: list, terms: list) -> int:
    count = 0
    for i, tok in enumerate(tokens):
        if tok in terms:
            count += _score_window(tokens, i)
    return count


def score_text(text: str) -> dict:
    """Score a single headline/text as bullish, bearish, or neutral.

    Returns score in [-1, 1].
    """
    if not text:
        return {"label": "neutral", "score": 0.0}

    tokens = _tokenize(text)
    bullish = _count_terms(tokens, BULLISH_TERMS)
    bearish = _count_terms(tokens, BEARISH_TERMS)

    total = bullish + bearish
    if total == 0:
        return {"label": "neutral", "score": 0.0}

    raw = (bullish - bearish) / (bullish + bearish)
    label = "bullish" if raw > 0.15 else ("bearish" if raw < -0.15 else "neutral")
    return {"label": label, "score": round(float(raw), 3)}


def score_news_items(news_items: list) -> dict:
    """Aggregate sentiment across a list of news items.

    Args:
        news_items: List of dicts each with a 'title' and/or 'summary' (or items
            with 'content.title'/'content.summary' like the yfmcp news shape).

    Returns:
        dict with aggregate score, label, and per-item detail count.
    """
    if not news_items:
        return {"label": "neutral", "score": 0.0, "items_scored": 0}

    scores = []
    for item in news_items:
        if isinstance(item, dict):
            content = item.get("content", item)
            text = content.get("title", "") if isinstance(content, dict) else ""
            if not text:
                text = item.get("title", "")
            summary = content.get("summary", "") if isinstance(content, dict) else item.get("summary", "")
            text = f"{text} {summary}".strip()
        else:
            text = str(item)
        result = score_text(text)
        if result["score"] != 0.0:
            scores.append(result["score"])

    if not scores:
        return {"label": "neutral", "score": 0.0, "items_scored": len(news_items)}

    aggregate = float(sum(scores) / len(scores))
    label = "bullish" if aggregate > 0.15 else ("bearish" if aggregate < -0.15 else "neutral")
    return {
        "label": label,
        "score": round(aggregate, 3),
        "items_scored": len(news_items),
        "items_with_signal": len(scores),
    }


def score_analyst_actions(actions: list) -> dict:
    """Score a list of analyst upgrade/downgrade actions.

    Args:
        actions: List of dicts with keys like 'action', 'toGrade'/'fromGrade',
            or 'ToGrade'/'FromGrade' (yfmcp shape).

    Returns:
        dict with aggregate analyst sentiment.
    """
    if not actions:
        return {"label": "neutral", "score": 0.0, "actions": 0}

    total = 0
    count = 0
    for action in actions:
        text = " ".join(
            str(action.get(k, "")) for k in
            ["action", "ToGrade", "toGrade", "FromGrade", "fromGrade"]
        )
        if not text.strip():
            continue
        result = score_text(text)
        total += result["score"]
        count += 1

    if count == 0:
        return {"label": "neutral", "score": 0.0, "actions": 0}

    aggregate = total / count
    label = "bullish" if aggregate > 0.15 else ("bearish" if aggregate < -0.15 else "neutral")
    return {"label": label, "score": round(float(aggregate), 3), "actions": count}
