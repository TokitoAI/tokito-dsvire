from dsvire.hostile_pdf import CASE_COUNT, generated_cases


def test_campaign_is_deterministic_unique_and_covers_mutation_classes() -> None:
    first = generated_cases()
    assert first == generated_cases()
    assert len(first) == CASE_COUNT
    assert len({payload for _, _, payload in first}) == CASE_COUNT
    assert {mutation for _, mutation, _ in first} == {
        "bit_flip",
        "zero_run",
        "truncate",
        "duplicate_slice",
        "token_replace",
        "append",
    }
    assert all(case_id == f"hostile-{index:03d}" for index, (case_id, _, _) in enumerate(first))
