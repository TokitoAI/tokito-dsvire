from dsvire.trace import TraceContext


def test_trace_context_is_strict_and_children_preserve_trace() -> None:
    root = TraceContext.parse(
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    )
    assert root is not None
    child = root.child()
    assert child.trace_id == root.trace_id
    assert child.parent_id != root.parent_id
    for invalid in (
        "00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
    ):
        assert TraceContext.parse(invalid) is None
