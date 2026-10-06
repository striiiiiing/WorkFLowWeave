from concurrent.futures import ThreadPoolExecutor

import pytest

from workflowweave.storage_primitives.jsonl import (
    JsonlStore,
    append_record,
    parse_records,
    read_records,
)


def test_concurrent_append_assigns_contiguous_ids(tmp_path):
    path = tmp_path / "events.jsonl"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda number: append_record(path, {"value": number}), range(64)))

    records = read_records(path)
    assert [item["id"] for item in records] == list(range(1, 65))
    assert {item["value"] for item in records} == set(range(64))


@pytest.mark.parametrize("payload", [
    b'{"id":1}\n{"id":3}\n',
    b'{"id":1}',
    b'{"id":true}\n',
    b'{broken}\n',
])
def test_parser_fails_closed_on_partial_or_invalid_log(payload):
    with pytest.raises((ValueError, UnicodeError)):
        parse_records(payload)


def test_append_does_not_accept_caller_owned_sequence(tmp_path):
    with pytest.raises(ValueError, match="already contains"):
        append_record(tmp_path / "events.jsonl", {"id": 42, "value": "x"})


@pytest.mark.asyncio
async def test_wait_after_closes_local_append_subscribe_gap(tmp_path):
    store = JsonlStore(tmp_path / "events.jsonl")
    read_after = store.read_after
    first_read = True

    async def append_between_read_and_subscribe(sequence):
        nonlocal first_read
        records = await read_after(sequence)
        if first_read and not records:
            first_read = False
            await store.append({"value": "local"})
        return records

    store.read_after = append_between_read_and_subscribe
    assert await store.wait_after(0, wait_seconds=1, poll_interval=0.05) == [
        {"id": 1, "value": "local"}
    ]


@pytest.mark.asyncio
async def test_wait_after_observes_another_store_instance(tmp_path):
    path = tmp_path / "events.jsonl"
    subscriber = JsonlStore(path)
    writer = JsonlStore(path)
    read_after = subscriber.read_after
    first_read = True

    async def append_from_another_instance(sequence):
        nonlocal first_read
        records = await read_after(sequence)
        if first_read and not records:
            first_read = False
            await writer.append({"value": "other process"})
        return records

    subscriber.read_after = append_from_another_instance
    assert await subscriber.wait_after(0, wait_seconds=1, poll_interval=0.01) == [
        {"id": 1, "value": "other process"}
    ]
