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
    M211_GET_IDS,
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
    """Guid.Empty.ToByteArray() as used by Express Labels on disconnect."""
    return bytes(16)


def chunk_payload_size(mtu_size: int) -> int:
    """Usable payload bytes per GATT write for the 3-byte Apollo header.

    Bleak's ``mtu_size`` is the negotiated ATT MTU. The attribute value may be
    at most ``mtu_size - 3``. Subtract the Apollo chunk header as well.
    Floor at 16 so a 23-byte default MTU (typical for some proxies) still works.
    Cap at 148 to match the Web SDK and live M211 indications (~153-byte ATT
    payloads / ~156-byte MTU on BlueZ).
    """
    att_value = max(mtu_size - ATT_HEADER_BYTES, 20)
    usable = max(att_value - CHUNK_HEADER_BYTES, 16)
    return min(usable, 148)


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


def chunk_write_with_response(flags: int, seq: int, *, retrying: bool = False) -> bool:
    """Match Android: write-with-response on seq 0, FLUSH, LAST, and retries."""
    return retrying or seq == 0 or flags in (CHUNK_FLAG_FLUSH, CHUNK_FLAG_LAST)


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


def build_get_packet(property_ids: tuple[str, ...] = M211_GET_IDS) -> bytes:
    """PropertyGetRequests packet to force an immediate Compact PICL dump."""
    body = {"PropertyGetRequests": [{"ID": prop_id} for prop_id in property_ids]}
    return build_picl_packet(json.dumps(body, separators=(",", ":")))


def build_set_packet(prop_id: str, value: str, *, quoted: bool = True) -> bytes:
    """PropertySetRequests packet (feed, cut, clear errors, timeout)."""
    if quoted:
        body = {"PropertySetRequests": [{"ID": prop_id, "Value": value}]}
        return build_picl_packet(json.dumps(body, separators=(",", ":")))
    body_text = '{"PropertySetRequests":[{"ID":"' + prop_id + '","Value":' + value + "}]}"
    return build_picl_packet(body_text)


def extract_picl_json(data: bytes) -> str:
    """Return the UTF-8 JSON body from a Compact PICL envelope, if any."""
    return _extract_json_text(data)


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


class PiclAssembler:
    """Reassemble Compact PICL indications that BlueZ splits at the ATT MTU."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def reset(self) -> None:
        self._buf.clear()

    @property
    def buffered(self) -> int:
        return len(self._buf)

    def feed(self, data: bytes) -> list[bytes]:
        """Return complete Compact PICL envelopes (GUID + length + JSON)."""
        if not data:
            return []
        self._buf.extend(data)
        complete: list[bytes] = []
        while True:
            packet = self._next_packet()
            if packet is None:
                break
            complete.append(packet)
        return complete

    def _next_packet(self) -> bytes | None:
        if len(self._buf) < 20:
            return None
        if bytes(self._buf[:16]) != COMPACT_PICL_GUID:
            idx = bytes(self._buf).find(COMPACT_PICL_GUID)
            if idx == -1:
                if len(self._buf) > 15:
                    del self._buf[:-15]
                return None
            del self._buf[:idx]
            if len(self._buf) < 20:
                return None
        length = int.from_bytes(self._buf[16:20], "little")
        if length > 65535:
            self._buf.clear()
            return None
        total = 20 + length
        if len(self._buf) < total:
            return None
        packet = bytes(self._buf[:total])
        del self._buf[:total]
        return packet
