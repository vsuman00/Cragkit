"""Synthetic dated price-review mechanics; no current-price or billing evidence."""
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluation_pricing as pricing

TODAY = date(2040, 2, 29)


def review():
    return dict(revision='ECR-price-r1', reviewed_on=TODAY.isoformat(),
        openai=dict(model='text-embedding-3-small', usd_per_million_input_tokens='0.02',
            source='https://developers.openai.com/api/docs/models/text-embedding-3-small'),
        cohere=dict(model='rerank-v5.0-fast', usd_per_million_input_tokens='0.02',
            source='https://cohere.com/blog/rerank-5'))


def test_exact_review_returns_isolated_fresh_snapshot():
    original = review()
    result = pricing.validate_price_review(original, today=TODAY)
    assert result == original and result is not original and result['openai'] is not original['openai']
    original['openai']['model'] = 'changed'
    result['cohere']['source'] = 'changed'
    assert pricing.validate_price_review(review(), today=TODAY) == review()


@pytest.mark.parametrize('day', ['2040-02-28', '2040-03-01', '2040-02-30', '2040-2-29',
    '2040-02-29T00:00:00Z', '2040-W09-3', '', None, 20400229])
def test_stale_future_or_malformed_dates_refused(day):
    value = review();value['reviewed_on'] = day
    with pytest.raises(pricing.PricingReviewError, match='^evaluation_price_review_invalid$'):
        pricing.validate_price_review(value, today=TODAY)


@pytest.mark.parametrize('change', ['extra','missing','revision','provider_extra','provider_missing',
    'provider_list','wrong_model','other_source','rate_number','rate_spelling','rate_increase','bool','list'])
def test_closed_schema_and_exact_provider_prices(change):
    value = review()
    if change == 'extra':value['billing'] = 'known'
    elif change == 'missing':del value['openai']
    elif change == 'revision':value['revision'] = 'later'
    elif change == 'provider_extra':value['cohere']['discount'] = '0'
    elif change == 'provider_missing':del value['cohere']['model']
    elif change == 'provider_list':value['cohere'] = []
    elif change == 'wrong_model':value['openai']['model'] = 'other'
    elif change == 'other_source':value['openai']['source'] = 'https://private.invalid'
    elif change == 'rate_number':value['openai']['usd_per_million_input_tokens'] = .02
    elif change == 'rate_spelling':value['openai']['usd_per_million_input_tokens'] = '0.020'
    elif change == 'rate_increase':value['cohere']['usd_per_million_input_tokens'] = '0.03'
    elif change == 'bool':value = True
    else:value = []
    with pytest.raises(pricing.PricingReviewError) as caught:
        pricing.validate_price_review(value, today=TODAY)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.mark.parametrize('today', ['2040-02-29', True, datetime(2040, 2, 29), 0])
def test_injected_day_requires_exact_date(today):
    with pytest.raises(pricing.PricingReviewError):pricing.validate_price_review(review(), today=today)


def test_default_uses_utc_date(monkeypatch):
    class Clock:
        @staticmethod
        def now(zone):
            assert zone is timezone.utc
            return datetime(2040, 2, 29, 23, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(pricing, 'datetime', Clock)
    assert pricing.validate_price_review(review()) == review()


def test_bounded_file_roundtrip(tmp_path):
    path = tmp_path/'price.json';path.write_text(json.dumps(review()))
    assert pricing.load_price_review(path, today=TODAY) == review()


@pytest.mark.parametrize('kind',['missing','oversized','invalid_json','duplicate','nonfinite','symlink','ancestor_symlink','fifo','directory','invalid_utf8'])
def test_unsafe_files_and_parser_errors_are_fixed_context_free(tmp_path,kind):
    path = tmp_path/'price.json'
    if kind == 'oversized':path.write_bytes(b' '*4097)
    elif kind == 'invalid_json':path.write_text('{private broken JSON')
    elif kind == 'duplicate':path.write_text('{"revision":"a","revision":"b"}')
    elif kind == 'nonfinite':path.write_text('{"private":NaN}')
    elif kind == 'symlink':
        target = tmp_path/'real.json';target.write_text(json.dumps(review()));path.symlink_to(target)
    elif kind == 'ancestor_symlink':
        actual = tmp_path/'real';actual.mkdir();(actual/'price.json').write_text(json.dumps(review()))
        link = tmp_path/'linked';link.symlink_to(actual, target_is_directory=True);path=link/'price.json'
    elif kind == 'fifo':os.mkfifo(path)
    elif kind == 'directory':path.mkdir()
    elif kind == 'invalid_utf8':path.write_bytes(b'private\xff')
    with pytest.raises(pricing.PricingReviewError,match='^evaluation_price_review_invalid$') as caught:
        pricing.load_price_review(path, today=TODAY)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
