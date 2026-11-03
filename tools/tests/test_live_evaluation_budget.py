"""Exact fixed admission and uncertain-work accounting; no I/O or billing claim."""
from pathlib import Path
import sys
from decimal import localcontext, Inexact, ROUND_FLOOR

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_evaluation_budget as M


def test_exact_provider_and_total_caps():
    budget = M.LiveEvaluationBudget()
    budget.abort(budget.begin('openai', 500000))
    before = budget.snapshot()
    with pytest.raises(M.LiveBudgetError, match='exhausted'):
        budget.begin('openai', 1)
    assert budget.snapshot() == before
    budget.settle(budget.begin('cohere', 500000))
    assert budget.snapshot()['estimated_cost_usd'] == '0.02'
    assert budget.snapshot()['providers']['openai']['estimated_cost_usd'] == '0.01'
    before = budget.snapshot()
    with pytest.raises(M.LiveBudgetError, match='exhausted'):
        budget.begin('cohere', 1)
    assert budget.snapshot() == before


def test_reconciliation_reduces_estimate_but_never_attempt_count():
    budget = M.LiveEvaluationBudget()
    budget.settle(budget.begin('openai', 500000), 0)
    budget.abort(budget.begin('openai', 500000))
    snapshot = budget.snapshot()
    assert snapshot['attempts'] == 2 and snapshot['estimated_cost_usd'] == '0.01'
    assert snapshot['admission_ceiling_usd'] == '0.02'
    assert snapshot['providers']['openai']['admission_ceiling_usd'] == '0.02'
    assert snapshot['actual_billing'] == 'unknown'
    assert snapshot['providers']['openai']['reported_attempts'] == 1
    assert snapshot['providers']['openai']['unknown_attempts'] == 1


def test_sixty_attempts_even_with_zero_reported_cost():
    budget = M.LiveEvaluationBudget()
    for _ in range(60):
        budget.settle(budget.begin('openai', 1), 0)
    before = budget.snapshot()
    with pytest.raises(M.LiveBudgetError, match='exhausted'):
        budget.begin('cohere', 1)
    assert budget.snapshot() == before and before['attempts'] == 60


@pytest.mark.parametrize('provider,tokens', [('other',1),(True,1),([],1),('openai',True),('openai',0),('openai',-1),('openai',1.0),('openai',float('nan')),('openai',float('inf')),('openai',2147483648)])
def test_invalid_admission_never_changes_state(provider, tokens):
    budget = M.LiveEvaluationBudget()
    before = budget.snapshot()
    with pytest.raises(M.LiveBudgetError, match='invalid'):
        budget.begin(provider, tokens)
    assert budget.snapshot() == before


def test_concurrent_foreign_forged_duplicate_tokens_do_not_damage_pending():
    budget, other = M.LiveEvaluationBudget(), M.LiveEvaluationBudget()
    token, foreign = budget.begin('openai',100), other.begin('cohere',100)
    before = budget.snapshot()
    with pytest.raises(M.LiveBudgetError, match='pending'):
        budget.begin('cohere',1)
    for forged in (foreign, object(), [], 1, None):
        for method in (budget.settle, budget.abort):
            with pytest.raises(M.LiveBudgetError, match='reservation_invalid'):
                method(forged)
            assert budget.snapshot() == before
    budget.settle(token, 2)
    replacement = budget.begin('cohere',100)
    before = budget.snapshot()
    for method in (budget.settle, budget.abort):
        with pytest.raises(M.LiveBudgetError, match='reservation_invalid'):
            method(token)
        assert budget.snapshot() == before
    budget.abort(replacement)


@pytest.mark.parametrize('method', ['abort', 'settle'])
def test_unknown_work_keeps_full_bound(method):
    budget = M.LiveEvaluationBudget()
    token = budget.begin('cohere',32768)
    getattr(budget,method)(token)
    record = budget.snapshot()['records'][0]
    assert record['estimated_input_tokens'] == 32768
    assert record['reported_input_tokens'] is None
    assert record['estimated_cost_usd'] == '0.00065536'


@pytest.mark.parametrize('usage', [True,-1,1.0,float('nan'),float('inf'),'1',2147483648])
def test_invalid_usage_freezes_and_keeps_original_ceiling(usage):
    budget = M.LiveEvaluationBudget()
    token = budget.begin('openai',100)
    with pytest.raises(M.LiveBudgetError, match='usage_invalid'):
        budget.settle(token,usage)
    snap = budget.snapshot()
    assert snap['closed'] and snap['pending'] == 0
    assert snap['records'][0]['estimated_input_tokens'] == 100
    assert snap['estimated_cost_usd'] == '0.000002'
    with pytest.raises(M.LiveBudgetError, match='closed'):
        budget.begin('cohere',1)


def test_bounded_integer_overrun_records_larger_estimate_and_freezes():
    budget = M.LiveEvaluationBudget()
    token = budget.begin('cohere',1)
    with pytest.raises(M.LiveBudgetError, match='overrun'):
        budget.settle(token,2147483647)
    snap = budget.snapshot()
    assert snap['closed'] and snap['pending'] == 0
    assert snap['estimated_cost_usd'] == '42.94967294'
    assert snap['records'][0]['reported_input_tokens'] == 2147483647
    assert snap['records'][0]['admission_ceiling_usd'] == '0.00000002'
    assert snap['providers']['cohere']['overrun_attempts'] == 1


def test_snapshot_isolation_and_caller_decimal_context_do_not_change_accounting():
    budget = M.LiveEvaluationBudget()
    with localcontext() as caller:
        caller.prec = 2
        caller.rounding = ROUND_FLOOR
        caller.traps[Inexact] = True
        caller.Emin, caller.Emax = -2, 2
        token = budget.begin('openai',32768)
        budget.settle(token,10001)
        snap = budget.snapshot()
    assert snap['estimated_cost_usd'] == '0.00020002'
    snap['providers']['openai']['estimated_cost_usd'] = '0'
    snap['records'][0]['estimated_input_tokens'] = 0
    snap['limits']['attempts'] = 1000000
    assert budget.snapshot()['estimated_cost_usd'] == '0.00020002'
    assert budget.snapshot()['limits']['attempts'] == 60
