import hashlib

GENESIS_HASH: bytes = b"\x00" * 32


def compute_row_hash(prev_hash: bytes, source: str, external_id: str, payload_bytes: bytes) -> bytes:
    """Hash canonical form: prev_hash || source || NUL || external_id || NUL || payload."""
    h = hashlib.sha256()
    h.update(prev_hash)
    h.update(source.encode("utf-8"))
    h.update(b"\x00")
    h.update(external_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(payload_bytes)
    return h.digest()
