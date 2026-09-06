from __future__ import annotations

import json
import uuid
from brady_m211.const import (
    CHUNK_FLAG_FLUSH,
    CHUNK_FLAG_LAST,
    CHUNK_FLAG_MORE,
    COMPACT_PICL_GUID,
    PROP_CUT,
    PROP_FEED,
    PROP_KNOCKOFF,
)
from brady_m211.models import PrinterStatus
from brady_m211.protocol import (
    PiclAssembler,
    build_get_packet,
    build_picl_packet,
    build_session_payload,
    build_set_packet,
    build_subscribe_packet,
    chunk_payload_size,
    chunk_write_with_response,
    guid_to_dotnet_bytes,
    is_m211_name,
    iter_chunks,
    parse_picl_notification,
    release_session_payload,
)
from brady_m211.vgl import (
    encode_rle_row,
    encode_vgl6_job,
    pack_raw_row,
)


def test_m211_name_filter() -> None:
    assert is_m211_name("M211-AB12")
    assert is_m211_name("Brady M211")
    assert not is_m211_name("M611")
    assert not is_m211_name(None)


def test_dotnet_guid_layout() -> None:
    guid = uuid.UUID("aabbccdd-eeff-1122-3344-556677889900")
    assert guid_to_dotnet_bytes(guid) == bytes.fromhex(
        "ddccbbaaffee22113344556677889900"
    )


def test_session_payload_claim_and_reuse() -> None:
    guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    first = build_session_payload(guid, True)
    reuse = build_session_payload(guid, False)
    assert len(first) == 17
    assert first[-1] == 0x01
    assert reuse[-1] == 0x00
    assert first[:-1] == reuse[:-1]
    assert release_session_payload() == bytes(16)


def test_chunk_write_with_response_matches_android() -> None:
    assert chunk_write_with_response(CHUNK_FLAG_MORE, 0) is True
    assert chunk_write_with_response(CHUNK_FLAG_MORE, 1) is False
    assert chunk_write_with_response(CHUNK_FLAG_FLUSH, 5) is True
    assert chunk_write_with_response(CHUNK_FLAG_LAST, 9) is True
    assert chunk_write_with_response(CHUNK_FLAG_MORE, 2, retrying=True) is True


def test_chunking_last_and_flush() -> None:
    payload = bytes(range(256)) * 20  # 5120 bytes
    chunks = list(iter_chunks(payload, payload_size=148, flush_every_bytes=4096))
    assert chunks[0][0] == CHUNK_FLAG_MORE
    flags = [chunk[0] for chunk in chunks]
    assert CHUNK_FLAG_FLUSH in flags
    assert flags[-1] == CHUNK_FLAG_LAST
    seq = chunks[1][1] | (chunks[1][2] << 8)
    assert seq == 1
    rebuilt = b"".join(chunk[3:] for chunk in chunks)
    assert rebuilt == payload


def test_chunk_payload_size_default_mtu() -> None:
    assert chunk_payload_size(23) >= 16
    assert chunk_payload_size(156) == 148
    assert chunk_payload_size(517) == 148


def test_picl_subscribe_and_set_packets() -> None:
    subscribe = build_subscribe_packet()
    assert subscribe.startswith(COMPACT_PICL_GUID)
    length = int.from_bytes(subscribe[16:20], "little")
    body = json.loads(subscribe[20 : 20 + length])
    assert "PropertySubscribeRequests" in body
    ids = [item["ID"] for item in body["PropertySubscribeRequests"]]
    assert PROP_KNOCKOFF in ids
    assert ids[-1] == PROP_KNOCKOFF
    feed = build_set_packet(PROP_FEED, "True")
    cut = build_set_packet(PROP_CUT, "True")
    assert b"0007" in feed
    assert b"0004" in cut
    feed_len = int.from_bytes(feed[16:20], "little")
    feed_body = json.loads(feed[20 : 20 + feed_len])
    assert feed_body["PropertySetRequests"][0]["Value"] == "True"
    getter = build_get_packet()
    assert getter.startswith(COMPACT_PICL_GUID)
    get_len = int.from_bytes(getter[16:20], "little")
    get_body = json.loads(getter[20 : 20 + get_len])
    assert "PropertyGetRequests" in get_body


def test_parse_picl_with_envelope_and_prefix() -> None:
    inner = json.dumps(
        {"PropertyGetResponses": [{"ID": "000C", "Value": "50", "Status": "Successful"}]}
    ).encode()
    packet = COMPACT_PICL_GUID + len(inner).to_bytes(4, "little") + inner
    parsed = parse_picl_notification(packet)
    assert parsed == [("000C", "50", "Successful")]

    noisy = b"xx" + inner
    parsed_noisy = parse_picl_notification(noisy)
    assert parsed_noisy[0][0] == "000C"


def test_picl_assembler_reassembles_mtu_fragments() -> None:
    inner = json.dumps(
        {
            "PropertyGetResponses": [
                {"ID": f"{i:04X}", "Value": "False", "Status": "Successful"}
                for i in range(1, 25)
            ]
        },
        separators=(",", ":"),
    )
    packet = build_picl_packet(inner)
    assert len(packet) > 153
    assembler = PiclAssembler()
    fragments = [packet[i : i + 153] for i in range(0, len(packet), 153)]
    parsed: list[tuple[str, str, str]] = []
    for index, fragment in enumerate(fragments):
        complete = assembler.feed(fragment)
        if index < len(fragments) - 1:
            assert complete == []
        else:
            assert len(complete) == 1
            parsed = parse_picl_notification(complete[0])
    assert len(parsed) == 24
    assert parsed[0][0] == "0001"
    assert assembler.buffered == 0


def test_status_from_properties() -> None:
    status = PrinterStatus.from_properties(
        {"0001": "87%", "000C": "128", "0006": "False", "0025": "True"}
    )
    assert status.printable_width == 128
    assert status.fatal_error is False
    assert status.media_out is True
    assert status.has_error is True
    assert status.print_blocked_reason() == "media is out"
    empty_media = PrinterStatus.from_properties({"001C": "True"})
    assert empty_media.print_blocked_reason() == "media remaining is empty"


def test_rle_and_vgl_job_roundtrip_shape() -> None:
    row = [1, 1, 1, 0, 0, 0, 0, 0]
    rle = encode_rle_row(row)
    assert rle[0] == 0x80 | 2
    assert rle[1] == 0x00 | 4
    raw = pack_raw_row(row)
    assert raw == bytes([0b11100000])
    rows = [row, row, [0] * 8]
    job = encode_vgl6_job(
        rows,
        page_width=8,
        page_height=3,
        printable_width=8,
        printable_height=3,
        job_name="HA",
    )
    assert job[:4] == b"\x01\x00\x00\x00"
    assert b"IBUlbl1" in job
    assert b"HA" in job
    assert job.endswith(b"\x02A\x02G")
