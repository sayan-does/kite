from dataclasses import dataclass
from typing import Literal

from app.db import supabase


@dataclass
class WeightedInterest:
    topic: str
    source: Literal["interest", "stack"]
    weight: float


def _interleave(interests: list[WeightedInterest], stacks: list[WeightedInterest]) -> list[WeightedInterest]:
    """Order topics so allocating N slots yields ~60% interest / ~40% stack."""
    result: list[WeightedInterest] = []
    i_idx, s_idx = 0, 0
    while i_idx < len(interests) or s_idx < len(stacks):
        for _ in range(3):
            if i_idx < len(interests):
                result.append(interests[i_idx])
                i_idx += 1
        for _ in range(2):
            if s_idx < len(stacks):
                result.append(stacks[s_idx])
                s_idx += 1
    return result


def resolve_interests(user_id: str) -> list[WeightedInterest]:
    interest_rows = (
        supabase.table("user_interests")
        .select("interest_tags(name)")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    interest_topics = sorted(
        {
            row["interest_tags"]["name"]
            for row in interest_rows
            if row.get("interest_tags") and row["interest_tags"].get("name")
        }
    )

    stack_rows = (
        supabase.table("tracked_dependencies")
        .select("package_name")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    stack_topics = sorted({row["package_name"] for row in stack_rows if row.get("package_name")})

    if not interest_topics and not stack_topics:
        return []

    if not stack_topics:
        w = 1.0 / len(interest_topics)
        return [WeightedInterest(topic=t, source="interest", weight=w) for t in interest_topics]

    if not interest_topics:
        w = 1.0 / len(stack_topics)
        return [WeightedInterest(topic=t, source="stack", weight=w) for t in stack_topics]

    interest_weight = 0.6 / len(interest_topics)
    stack_weight = 0.4 / len(stack_topics)
    interests = [WeightedInterest(topic=t, source="interest", weight=interest_weight) for t in interest_topics]
    stacks = [WeightedInterest(topic=t, source="stack", weight=stack_weight) for t in stack_topics]
    return _interleave(interests, stacks)
