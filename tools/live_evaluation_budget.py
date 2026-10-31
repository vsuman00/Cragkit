"""Pure fixed-cap admission accounting for the dated LEIO-r1 evaluation."""
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

_PROVIDERS = ('openai', 'cohere')
_MAX_TOKENS = 2147483647
_MAX_ATTEMPTS = 60
_TOTAL_LIMIT = Decimal('0.02')
_PROVIDER_LIMIT = Decimal('0.01')
_PRICE_PER_MILLION = Decimal('0.02')


class LiveBudgetError(ValueError):
    """Fixed, payload-free admission or reconciliation error."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _cost(tokens):
    # Isolate precision, rounding, exponent bounds and traps from caller state.
    context = Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                      capitals=1, clamp=0, flags=[], traps=[])
    with localcontext(context):
        return Decimal(tokens) * _PRICE_PER_MILLION / Decimal(1000000)


def _amount(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


@dataclass
class _Attempt:
    provider: str
    ceiling: int
    estimate: int
    reported: int | None = None
    state: str = 'pending'
    usage: str = 'unknown'


class LiveEvaluationBudget:
    """At most USD0.02 total, USD0.01/provider, 60 attempts and one pending."""
    def __init__(self):
        self._attempts = {}
        self._pending = None
        self._closed = False

    def _tokens(self, *, provider=None):
        return sum(attempt.estimate for attempt in self._attempts.values()
                   if provider is None or attempt.provider == provider)

    def _reservation(self, reservation):
        if type(reservation) is not object:
            raise LiveBudgetError('live_budget_reservation_invalid')
        attempt = self._attempts.get(reservation)
        if attempt is None or attempt.state != 'pending' or reservation is not self._pending:
            raise LiveBudgetError('live_budget_reservation_invalid')
        return attempt

    def begin(self, provider, input_token_ceiling):
        if (type(provider) is not str or provider not in _PROVIDERS
                or type(input_token_ceiling) is not int or not 1 <= input_token_ceiling <= _MAX_TOKENS):
            raise LiveBudgetError('live_budget_invalid')
        if self._closed:
            raise LiveBudgetError('live_budget_closed')
        if self._pending is not None:
            raise LiveBudgetError('live_budget_pending')
        if (len(self._attempts) >= _MAX_ATTEMPTS
                or _cost(self._tokens() + input_token_ceiling) > _TOTAL_LIMIT
                or _cost(self._tokens(provider=provider) + input_token_ceiling) > _PROVIDER_LIMIT):
            raise LiveBudgetError('live_budget_exhausted')
        reservation = object()
        self._attempts[reservation] = _Attempt(provider, input_token_ceiling, input_token_ceiling)
        self._pending = reservation
        return reservation

    def settle(self, reservation, reported_input_tokens=None):
        attempt = self._reservation(reservation)
        if reported_input_tokens is None:
            attempt.state = 'settled'
            self._pending = None
            return
        if type(reported_input_tokens) is not int or not 0 <= reported_input_tokens <= _MAX_TOKENS:
            attempt.state, attempt.usage = 'invalid_usage', 'invalid'
            self._pending, self._closed = None, True
            raise LiveBudgetError('live_budget_usage_invalid')
        attempt.reported = reported_input_tokens
        attempt.estimate = reported_input_tokens
        self._pending = None
        if reported_input_tokens > attempt.ceiling:
            attempt.state, attempt.usage = 'overrun', 'overrun'
            self._closed = True
            raise LiveBudgetError('live_budget_overrun')
        attempt.state, attempt.usage = 'settled', 'reported'

    def abort(self, reservation):
        attempt = self._reservation(reservation)
        attempt.state = 'aborted'
        self._pending = None

    def snapshot(self):
        records = [dict(provider=attempt.provider, input_token_ceiling=attempt.ceiling,
            reported_input_tokens=attempt.reported, estimated_input_tokens=attempt.estimate,
            admission_ceiling_usd=_amount(_cost(attempt.ceiling)),
            estimated_cost_usd=_amount(_cost(attempt.estimate)), state=attempt.state,
            usage_state=attempt.usage) for attempt in self._attempts.values()]
        providers = {}
        for provider in _PROVIDERS:
            selected = [record for record in records if record['provider'] == provider]
            providers[provider] = dict(attempts=len(selected),
                pending=sum(record['state'] == 'pending' for record in selected),
                admitted_input_token_ceilings=sum(record['input_token_ceiling'] for record in selected),
                estimated_input_tokens=sum(record['estimated_input_tokens'] for record in selected),
                admission_ceiling_usd=_amount(_cost(sum(record['input_token_ceiling'] for record in selected))),
                estimated_cost_usd=_amount(_cost(self._tokens(provider=provider))),
                reported_attempts=sum(record['usage_state'] == 'reported' for record in selected),
                unknown_attempts=sum(record['reported_input_tokens'] is None for record in selected),
                overrun_attempts=sum(record['usage_state'] == 'overrun' for record in selected))
        return dict(attempts=len(records), pending=int(self._pending is not None), closed=self._closed,
            estimated_cost_usd=_amount(_cost(self._tokens())),
            admission_ceiling_usd=_amount(_cost(sum(record['input_token_ceiling'] for record in records))),
            limits=dict(total_usd='0.02', provider_usd='0.01', attempts=60, pending=1),
            price_usd_per_million_input_tokens='0.02', price_date='2026-10-31',
            actual_billing='unknown', providers=providers, records=records)
