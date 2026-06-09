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


def test_spawn_pipeline_omits_force_for_data_pipeline(monkeypatch):
    """데이터 파이프라인 모듈(kr_pipeline.pipeline 등)은 --force 인자를 정의하지 않아
    argparse 가 'unrecognized arguments: --force' 로 즉시 종료한다(exit 2). 그러면
    run_tracking 이 running 행을 만들기 전에 죽어 UI 에 실행중/로그가 안 뜬다.
    데이터 파이프라인의 중복 방지는 API 레이어(check_can_run_pipeline)가 전담하고
    모듈엔 자체 force 가 없으므로, force=True 라도 --force 를 모듈에 넘기면 안 된다.
    """
    import api.services.runner_service as rs
    captured = {}
    class _Proc:
        pid = 123
    def _fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _Proc()
    monkeypatch.setattr(rs.subprocess, "Popen", _fake_popen)
    rs.spawn_pipeline("data-daily", "default", params=None, force=True)
    assert "kr_pipeline.pipeline" in captured["cmd"]
    assert "--force" not in captured["cmd"]
