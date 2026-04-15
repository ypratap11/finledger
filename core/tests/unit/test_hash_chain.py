import hashlib
from finledger.ingest.hash_chain import compute_row_hash, GENESIS_HASH


def test_genesis_hash_is_zero_bytes():
    assert GENESIS_HASH == b"\x00" * 32


def test_row_hash_is_deterministic():
    prev = GENESIS_HASH
    h1 = compute_row_hash(prev, "stripe", "evt_1", b'{"a":1}')
    h2 = compute_row_hash(prev, "stripe", "evt_1", b'{"a":1}')
    assert h1 == h2
    assert len(h1) == 32


def test_row_hash_depends_on_prev():
    h_a = compute_row_hash(GENESIS_HASH, "stripe", "evt_1", b"{}")
    h_b = compute_row_hash(h_a, "stripe", "evt_1", b"{}")
    assert h_a != h_b


def test_row_hash_depends_on_payload():
    a = compute_row_hash(GENESIS_HASH, "stripe", "evt_1", b'{"a":1}')
    b = compute_row_hash(GENESIS_HASH, "stripe", "evt_1", b'{"a":2}')
    assert a != b


def test_row_hash_matches_canonical_sha256():
    prev = GENESIS_HASH
    expected = hashlib.sha256(prev + b"stripe\x00evt_1\x00" + b'{"a":1}').digest()
    assert compute_row_hash(prev, "stripe", "evt_1", b'{"a":1}') == expected
