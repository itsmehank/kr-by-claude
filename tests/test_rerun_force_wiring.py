def test_spawn_pipeline_includes_force(monkeypatch):
    import api.services.runner_service as rs
    captured = {}
    class _Proc:
        pid = 123
    def _fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _Proc()
    monkeypatch.setattr(rs.subprocess, "Popen", _fake_popen)
    rs.spawn_pipeline("llm-full-daily", "default", params=None, force=True)
    assert "--force" in captured["cmd"]

def test_spawn_pipeline_omits_force_by_default(monkeypatch):
    import api.services.runner_service as rs
    captured = {}
    class _Proc:
        pid = 123
    def _fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _Proc()
    monkeypatch.setattr(rs.subprocess, "Popen", _fake_popen)
    rs.spawn_pipeline("llm-full-daily", "default", params=None)
    assert "--force" not in captured["cmd"]
