"""Explicit dated price-review metadata; no network or billing inference."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import re

from evaluation_packet import _read, _json


class PricingReviewError(ValueError):
    """Fixed diagnostic without retained file or parser details."""


def _invalid():
    raise PricingReviewError('evaluation_price_review_invalid')


_PROVIDERS = {
    'openai': {
        'model': 'text-embedding-3-small',
        'usd_per_million_input_tokens': '0.02',
        'source': 'https://developers.openai.com/api/docs/models/text-embedding-3-small',
    },
    'cohere': {
        'model': 'rerank-v5.0-fast',
        'usd_per_million_input_tokens': '0.02',
        'source': 'https://cohere.com/blog/rerank-5',
    },
}


def validate_price_review(value, *, today=None):
    """Match an explicit review to today's UTC date and fixed admission rates.

    This validates a caller's review record; it does not visit the cited sources
    or establish actual account billing. The live operator owns that review.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if type(today) is not date:
        _invalid()
    if (type(value) is not dict or set(value) != {'revision', 'reviewed_on', 'openai', 'cohere'}
            or type(value['revision']) is not str or value['revision'] != 'ECR-price-r1'
            or type(value['reviewed_on']) is not str
            or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value['reviewed_on']) is None
            or value['reviewed_on'] != today.isoformat()):
        _invalid()
    for provider, expected in _PROVIDERS.items():
        observed = value[provider]
        if (type(observed) is not dict or set(observed) != set(expected)
                or any(type(observed[key]) is not str or observed[key] != expected[key] for key in expected)):
            _invalid()
    return dict(revision='ECR-price-r1', reviewed_on=today.isoformat(),
                **{provider: dict(expected) for provider, expected in _PROVIDERS.items()})


def load_price_review(path, *, today=None):
    """Load one bounded regular JSON file without following path symlinks."""
    failed = False
    try:
        selected = Path(path).absolute()
        # Start at the filesystem anchor so _read checks every directory, even
        # when the caller selected a path containing a symlinked ancestor.
        anchor = Path(selected.anchor)
        raw = _read(anchor, str(selected.relative_to(anchor)), 4096)
        result = validate_price_review(_json(raw), today=today)
    except Exception:
        failed = True
    if failed:
        _invalid()
    return result
