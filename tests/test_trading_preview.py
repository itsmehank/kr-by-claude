from datetime import date
import re

import pytest

from kr_trading.preview import PreviewStore, canonical_hash, new_client_order_id
from kr_trading.toss.errors import GuardError


def test_client_order_id_format():
    cid = new_client_order_id(date(2026, 9, 14))
    assert re.fullmatch(r"20260914-[A-Za-z0-9]{8}", cid) and len(cid) <= 36
    assert new_client_order_id() != new_client_order_id()


def test_canonical_hash_is_order_independent():
    assert canonical_hash({"a": "1", "b": "2"}) == canonical_hash({"b": "2", "a": "1"})
    assert canonical_hash({"a": "1"}) != canonical_hash({"a": "2"})


def test_put_get_verify():
    now = [0.0]
    st = PreviewStore(ttl_sec=300, clock=lambda: now[0])
    payload = {"symbol": "005930", "price": "70000", "quantity": "10", "clientOrderId": "c1"}
    tok = st.put(payload, {"amount": "700000"})
    assert tok == canonical_hash(payload)
    assert st.verify(tok, payload) == {"amount": "700000"}
    with pytest.raises(GuardError) as ei:
        st.verify(tok, {**payload, "quantity": "100"})
    assert ei.value.code == "guard/preview-mismatch"
    now[0] = 301
    with pytest.raises(GuardError) as ei:
        st.verify(tok, payload)
    assert ei.value.code == "guard/preview-required"


def test_unknown_token_is_preview_required():
    with pytest.raises(GuardError) as ei:
        PreviewStore().verify("nope", {})
    assert ei.value.code == "guard/preview-required"


def test_consume_is_single_use():
    st = PreviewStore(ttl_sec=300, clock=lambda: 0.0)
    payload = {"symbol": "005930", "price": "70000", "quantity": "10", "clientOrderId": "c1"}
    tok = st.put(payload, {"amount": "700000"})
    assert st.consume(tok, payload) == {"amount": "700000"}
    with pytest.raises(GuardError) as ei:
        st.consume(tok, payload)
    assert ei.value.code == "guard/preview-required"
    with pytest.raises(GuardError) as ei:
        st.verify(tok, payload)
    assert ei.value.code == "guard/preview-required"


def test_put_evicts_expired():
    now = [0.0]
    st = PreviewStore(ttl_sec=300, clock=lambda: now[0])
    st.put({"a": 1}, {})
    now[0] = 301
    st.put({"b": 2}, {})
    assert len(st._items) == 1
