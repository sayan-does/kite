from unittest.mock import MagicMock, patch

from app.agents.discovery.interest_resolver import WeightedInterest, resolve_interests


def _mock_supabase(interests: list[str], stacks: list[str]):
    def table(name):
        mock = MagicMock()
        if name == "user_interests":
            mock.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"interest_tags": {"name": n}} for n in interests]
            )
        elif name == "tracked_dependencies":
            mock.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"package_name": p} for p in stacks]
            )
        return mock

    return table


def test_sixty_forty_split_across_many_picks():
    interests = ["Alpha", "Beta", "Gamma"]
    stacks = ["react", "vue"]
    with patch("app.agents.discovery.interest_resolver.supabase") as mock_sb:
        mock_sb.table.side_effect = _mock_supabase(interests, stacks)
        ranked = resolve_interests("user-1")

    assert len(ranked) == 5
    picks = ranked[:10]
    interest_count = sum(1 for p in picks if p.source == "interest")
    stack_count = sum(1 for p in picks if p.source == "stack")
    assert interest_count == 3
    assert stack_count == 2

    interest_weight = sum(p.weight for p in ranked if p.source == "interest")
    stack_weight = sum(p.weight for p in ranked if p.source == "stack")
    assert abs(interest_weight - 0.6) < 0.001
    assert abs(stack_weight - 0.4) < 0.001


def test_no_stack_falls_back_to_all_interests():
    with patch("app.agents.discovery.interest_resolver.supabase") as mock_sb:
        mock_sb.table.side_effect = _mock_supabase(["Frontend", "Backend"], [])
        ranked = resolve_interests("user-1")

    assert len(ranked) == 2
    assert all(p.source == "interest" for p in ranked)
    assert abs(sum(p.weight for p in ranked) - 1.0) < 0.001


def test_no_interests_falls_back_to_all_stack():
    with patch("app.agents.discovery.interest_resolver.supabase") as mock_sb:
        mock_sb.table.side_effect = _mock_supabase([], ["react", "lodash"])
        ranked = resolve_interests("user-1")

    assert len(ranked) == 2
    assert all(p.source == "stack" for p in ranked)
    assert abs(sum(p.weight for p in ranked) - 1.0) < 0.001


def test_ties_broken_by_name():
    with patch("app.agents.discovery.interest_resolver.supabase") as mock_sb:
        mock_sb.table.side_effect = _mock_supabase(["Zeta", "Alpha"], [])
        ranked = resolve_interests("user-1")

    topics = [p.topic for p in ranked]
    assert topics == ["Alpha", "Zeta"]


def test_interleave_pattern():
    interests = [WeightedInterest("A", "interest", 0.2), WeightedInterest("B", "interest", 0.2), WeightedInterest("C", "interest", 0.2)]
    stacks = [WeightedInterest("react", "stack", 0.2), WeightedInterest("vue", "stack", 0.2)]
    from app.agents.discovery.interest_resolver import _interleave

    ordered = _interleave(interests, stacks)
    sources = [x.source for x in ordered]
    assert sources[:5] == ["interest", "interest", "interest", "stack", "stack"]
