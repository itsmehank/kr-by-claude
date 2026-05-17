def test_slack_skips_when_no_webhook(mocker, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    mock_post = mocker.patch("urllib.request.urlopen")

    from kr_pipeline.llm_runner import slack
    import importlib
    importlib.reload(slack)
    from kr_pipeline.llm_runner.slack import notify_signal

    notify_signal(symbol="005930", name="삼성전자", entry_price=80000, stop_loss=76000)
    mock_post.assert_not_called()


def test_slack_posts_when_webhook_set(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_post = mocker.patch("urllib.request.urlopen")

    from kr_pipeline.llm_runner import slack
    import importlib
    importlib.reload(slack)
    from kr_pipeline.llm_runner.slack import notify_signal

    notify_signal(symbol="005930", name="삼성전자", entry_price=80000, stop_loss=76000)
    mock_post.assert_called_once()
