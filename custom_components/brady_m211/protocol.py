"""Byte-level Apollo helpers that do not depend on Home Assistant."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

from .const import (
    ATT_HEADER_BYTES,
    CHUNK_FLAG_FLUSH,
    CHUNK_FLAG_LAST,
    CHUNK_FLAG_MORE,
    CHUNK_HEADER_BYTES,
    COMPACT_PICL_GUID,
    FLUSH_EVERY_BYTES,
    M211_SUBSCRIBE_IDS,
)


class BradyProtocolError(Exception):
    """Invalid Brady protocol data."""


class BradyOwnershipError(Exception):
    """The M211 session is owned by another host."""


def is_m211_name(name: str | None) -> bool:
    """Return True if a BLE advertisement name looks like an M211."""
    if not name:
        return False
    return "M211" in name.upper()


def guid_to_dotnet_bytes(guid: uuid.UUID) -> bytes:
    """Encode a UUID in .NET System.Guid mixed-endian layout."""
    rfc = guid.bytes
    return bytes(
        [
            rfc[3],
            rfc[2],
            rfc[1],
            rfc[0],
            rfc[5],
            rfc[4],
            rfc[7],
            rfc[6],
            *rfc[8:],
        ]
    )


def build_session_payload(guid: uuid.UUID, first_claim: bool) -> bytes:
    """Build the 17-byte Session ID characteristic value."""
    flag = 0x01 if first_claim else 0x00
    return guid_to_dotnet_bytes(guid) + bytes([flag])


def release_session_payload() -> bytes:
    """Zeros that drop HA ownership so another client can claim the printer."""
    return bytes(17)


def chunk_payload_size(mtu_size: int) -> int:
    """Usable payload bytes per GATT write for the 3-byte Apollo header.

    Bleak's ``mtu_size`` is the negotiated ATT MTU. The attribute value may be
    at most ``mtu_size - 3``. Subtract the Apollo chunk header as well.
    Floor at 16 so a 23-byte default MTU (typical for some proxies) still works.
    """
    att_value = max(mtu_size - ATT_HEADER_BYTES, 20)
    return max(att_value - CHUNK_HEADER_BYTES, 16)


def iter_chunks(
    payload: bytes,
    payload_size: int,
    *,
    flush_every_bytes: int = FLUSH_EVERY_BYTES,
) -> Iterator[bytes]:
    """Yield Apollo GATT writes: ``[flags][seq u16 LE][data]``."""
    if payload_size < 1:
        raise BradyProtocolError("Chunk payload size must be at least 1")
    total = len(payload)
    offset = 0
    seq = 0
    since_flush = 0
    while offset < total:
        take = min(payload_size, total - offset)
        end = offset + take
        is_last = end >= total
        would_flush = (not is_last) and (since_flush + take >= flush_every_bytes)
        if is_last:
            flags = CHUNK_FLAG_LAST
        elif would_flush:
            flags = CHUNK_FLAG_FLUSH
        else:
            flags = CHUNK_FLAG_MORE
        header = bytes([flags, seq & 0xFF, (seq >> 8) & 0xFF])
        yield header + payload[offset:end]
        offset = end
        seq += 1
        if would_flush or is_last:
            since_flush = 0
        else:
            since_flush += take


def build_picl_packet(json_body: str) -> bytes:
    """Wrap Compact PICL JSON: GUID + little-endian length + UTF-8 JSON."""
    encoded = json_body.encode("utf-8")
    return COMPACT_PICL_GUID + len(encoded).to_bytes(4, "little") + encoded


def build_subscribe_packet(property_ids: tuple[str, ...] = M211_SUBSCRIBE_IDS) -> bytes:
    """Subscribe request for M211 Compact PICL properties."""
    body = {
        "PropertySubscribeRequests": [{"ID": prop_id} for prop_id in property_ids]
    }
    return build_picl_packet(json.dumps(body, separators=(",", ":")))


def build_set_packet(property_id: str, value: str) -> bytes:
    """PropertySetRequests packet used for feed/cut/clear."""
    body = {"PropertySetRequests": [{"ID": property_id, "Value": value}]}
    return build_picl_packet(json.dumps(body, separators=(",", ":")))


def parse_picl_notification(data: bytes) -> list[tuple[str, str, str]]:
    """Parse one or more Compact PICL indication payloads into (id, value, status)."""
    text = _extract_json_text(data)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        rebuilt = _rebuild_get_responses(text)
        if rebuilt is None:
            return []
        parsed = rebuilt
    responses = parsed.get("PropertyGetResponses") or parsed.get(
        "propertyGetResponses"
    )
    if not isinstance(responses, list):
        return []
    result: list[tuple[str, str, str]] = []
    for item in responses:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("ID") or item.get("Id") or "")
        value = str(item.get("Value", ""))
        status = str(item.get("Status", ""))
        if prop_id:
            result.append((prop_id, value, status))
    return result


def _extract_json_text(data: bytes) -> str:
    """Strip the Compact PICL binary envelope if present, else decode as UTF-8."""
    if len(data) >= 20 and data[:16] == COMPACT_PICL_GUID:
        length = int.from_bytes(data[16:20], "little")
        blob = data[20 : 20 + length]
        return blob.decode("utf-8", errors="replace")
    decoded = data.decode("utf-8", errors="replace").lstrip("\x00")
    return decoded


def _rebuild_get_responses(text: str) -> dict[str, object] | None:
    """Web SDK fallback when a notification is prefixed before ``PropertyGetResponses``."""
    marker = ":["
    if marker not in text:
        start = text.find("{")
        if start == -1:
            return None
        try:
            parsed = json.loads(text[start:])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    rebuilt = '{"PropertyGetResponses":[' + text.split(marker, 1)[1]
    try:
        parsed = json.loads(rebuilt)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
