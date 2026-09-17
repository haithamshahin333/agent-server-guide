from my_agent.echo import Context, graph


def test_echo_replies():
    out = graph.invoke({"messages": [{"role": "user", "content": "hi"}]})
    assert out["messages"][-1].content == "echo: hi"


def test_echo_uses_context():
    out = graph.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        context=Context(prefix="bot", shout=True),
    )
    assert out["messages"][-1].content == "BOT: HI"
