from agent import answer


def test_agent_returns_code():
    output = answer("Show an upload example")
    assert "python" in output
