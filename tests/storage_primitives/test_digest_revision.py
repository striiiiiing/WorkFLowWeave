import pytest

from logagent.storage_primitives.digest import canonical_json, digest_json
from logagent.storage_primitives.revision import etag_for_bytes, if_match, next_revision


def test_digest_uses_canonical_json_and_rejects_nan():
    assert canonical_json({"z": 1, "a": "值"}) == b'{"a":"\xe5\x80\xbc","z":1}'
    assert digest_json({"a": 1, "b": 2}) == digest_json({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        digest_json(float("nan"))


def test_etag_and_if_match_cover_create_replace_and_conflict():
    actual = etag_for_bytes(b"current")
    assert if_match(None, "*") is False
    assert if_match(actual, "*") is True
    assert if_match(actual, actual)
    assert if_match(actual, f'"other", {actual}')
    assert not if_match(actual, 'W/' + actual)
    assert not if_match(actual, '"stale"')
    with pytest.raises(ValueError):
        if_match(actual, "")


def test_revision_is_monotonic_and_rejects_invalid_values():
    assert next_revision(0) == 1
    assert next_revision(12) == 13
    for invalid in (-1, True, "1"):
        with pytest.raises(ValueError):
            next_revision(invalid)
