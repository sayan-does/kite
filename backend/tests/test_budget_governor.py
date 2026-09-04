from app.services.llm import BudgetGovernor, estimate_tokens


def test_spends_until_request_cap():
    gov = BudgetGovernor(max_requests=3, max_tokens=1_000_000)
    assert gov.try_spend(10)
    assert gov.try_spend(10)
    assert gov.try_spend(10)
    assert not gov.try_spend(10)
    assert gov.requests_used == 3


def test_spends_until_token_cap():
    gov = BudgetGovernor(max_requests=100, max_tokens=100)
    assert gov.try_spend(60)
    # 60 + 60 exceeds 100, so the second reservation is refused.
    assert not gov.try_spend(60)
    assert gov.try_spend(40)
    assert gov.tokens_used == 100


def test_refused_spend_does_not_consume_budget():
    gov = BudgetGovernor(max_requests=2, max_tokens=100)
    gov.try_spend(90)
    assert not gov.try_spend(50)
    assert gov.requests_used == 1
    assert gov.tokens_used == 90


def test_reset_cycle_restores_budget():
    gov = BudgetGovernor(max_requests=1, max_tokens=100)
    assert gov.try_spend(100)
    assert not gov.try_spend(1)
    gov.reset_cycle()
    assert gov.requests_used == 0
    assert gov.tokens_used == 0
    assert gov.try_spend(50)


def test_remaining_properties_never_go_negative():
    gov = BudgetGovernor(max_requests=1, max_tokens=10)
    gov.try_spend(10)
    assert gov.requests_remaining == 0
    assert gov.tokens_remaining == 0


def test_record_actual_reconciles_overestimate():
    gov = BudgetGovernor(max_requests=10, max_tokens=1000)
    gov.try_spend(500)
    gov.record_actual(actual_tokens=200, estimated_tokens=500)
    assert gov.tokens_used == 200


def test_record_actual_reconciles_underestimate():
    gov = BudgetGovernor(max_requests=10, max_tokens=1000)
    gov.try_spend(100)
    gov.record_actual(actual_tokens=300, estimated_tokens=100)
    assert gov.tokens_used == 300


def test_record_actual_clamps_at_zero():
    gov = BudgetGovernor(max_requests=10, max_tokens=1000)
    gov.try_spend(100)
    gov.record_actual(actual_tokens=0, estimated_tokens=500)
    assert gov.tokens_used == 0


def test_can_spend_does_not_mutate():
    gov = BudgetGovernor(max_requests=2, max_tokens=100)
    assert gov.can_spend(50)
    assert gov.requests_used == 0
    assert gov.tokens_used == 0


def test_estimate_tokens_scales_with_length():
    assert estimate_tokens("x" * 4000) > estimate_tokens("x" * 400)
