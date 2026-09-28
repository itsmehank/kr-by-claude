"""변경 감지 해시 — 제목·본문·코멘트·참조 상태만 입력, 라벨·시각은 제외."""
from api.services.issue_brief.github import IssueComment, IssueRaw, RefState
from api.services.issue_brief.hashing import content_hash, extract_refs


def _raw(number=10, title="t", body="", comments=()):
    return IssueRaw(number=number, title=title, body=body, labels=(),
                    updated_at="2026-09-27T00:00:00Z",
                    comments=tuple(IssueComment(b, "c") for b in comments))


def test_extract_refs_from_body_and_comments_excluding_self():
    raw = _raw(number=10, body="depends on #114 and #10, see PR #187.", comments=("also #5",))
    assert extract_refs(raw) == {114, 187, 5}


def test_extract_refs_ignores_non_issue_hash_tokens():
    raw = _raw(body="color #fff and heading # 3 and price #12abc")
    assert extract_refs(raw) == set()


def test_hash_is_stable_and_64_hex():
    raw = _raw(body="b")
    h1 = content_hash(raw, [RefState(1, "open", "x")])
    h2 = content_hash(raw, [RefState(1, "open", "x")])
    assert h1 == h2 and len(h1) == 64 and int(h1, 16) >= 0


def test_hash_changes_when_ref_state_changes_only():
    raw = _raw(body="after #114")
    assert content_hash(raw, [RefState(114, "open", "x")]) != \
           content_hash(raw, [RefState(114, "closed", "x")])


def test_hash_ignores_ref_order_and_ref_title():
    raw = _raw(body="#1 #2")
    a = content_hash(raw, [RefState(1, "open", "A"), RefState(2, "closed", "B")])
    b = content_hash(raw, [RefState(2, "closed", "ZZ"), RefState(1, "open", "YY")])
    assert a == b


def test_hash_changes_on_new_comment_and_ignores_updated_at_labels():
    base = _raw(body="b", comments=("c1",))
    more = _raw(body="b", comments=("c1", "c2"))
    assert content_hash(base, []) != content_hash(more, [])
    relabeled = IssueRaw(number=10, title="t", body="b", labels=("x",),
                         updated_at="2030-01-01T00:00:00Z",
                         comments=(IssueComment("c1", "other"),))
    assert content_hash(base, []) == content_hash(relabeled, [])


def test_hash_ignores_unknown_refs_not_sent_to_payload():
    raw = _raw(body="#1 #9999")
    a = content_hash(raw, [RefState(1, "open", ""), RefState(9999, "unknown", "")])
    b = content_hash(raw, [RefState(1, "open", "")])
    assert a == b


def test_extract_refs_with_korean_particles_and_no_space():
    raw = _raw(body="#114의 배치, #186와 동일, 이슈#120 참고, (#130) ok", comments=("#199은 종결",))
    assert extract_refs(raw) == {114, 186, 120, 130, 199}
