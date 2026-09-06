"""VGL/STX v6 print-job encoder for the Brady M211."""

from __future__ import annotations

import struct

from .const import DPI


def _ascii_u4(value: int) -> bytes:
    return f"{max(0, min(value, 9999)):04d}".encode("ascii")


def _ascii_signed3(value: int) -> bytes:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):02d}".encode("ascii")


def _stx(cmd: int, payload: bytes = b"") -> bytes:
    return bytes([0x02, cmd]) + payload


def _stx_k(sub: int, payload: bytes = b"") -> bytes:
    return bytes([0x02, 0x4B, 0x00, sub]) + payload


def pack_raw_row(pixels: list[int]) -> bytes:
    """Pack 1=black pixels into MSB-first bytes."""
    out = bytearray()
    byte = 0
    bit = 7
    for pixel in pixels:
        if pixel:
            byte |= 1 << bit
        bit -= 1
        if bit < 0:
            out.append(byte)
            byte = 0
            bit = 7
    if bit != 7:
        out.append(byte)
    return bytes(out)


def encode_rle_row(pixels: list[int]) -> bytes:
    """Brady VGL RLE: bit7 colour (1=black), bits6-0 = run-1 (max 128)."""
    out = bytearray()
    index = 0
    length = len(pixels)
    while index < length:
        colour = 1 if pixels[index] else 0
        run = 1
        index += 1
        while index < length and (1 if pixels[index] else 0) == colour and run < 128:
            run += 1
            index += 1
        out.append((0x80 if colour else 0x00) | (run - 1))
    return bytes(out)


def _row_commands(rows: list[list[int]]) -> bytes:
    body = bytearray()
    previous: list[int] | None = None
    repeat = 0
    for row in rows:
        if previous is not None and row == previous and repeat < 255:
            repeat += 1
            continue
        if repeat:
            body.extend(bytes([0x00, 0x00, 0xFF, repeat]))
            repeat = 0
        rle = encode_rle_row(row)
        raw = pack_raw_row(row)
        if len(rle) <= len(raw) and len(rle) <= 255:
            body.extend(bytes([0x81, len(rle)]))
            body.extend(rle)
        elif len(raw) <= 255:
            body.extend(bytes([0x80, len(raw)]))
            body.extend(raw)
        else:
            raise ValueError("Row is too wide for a single VGL command")
        previous = row
    if repeat:
        body.extend(bytes([0x00, 0x00, 0xFF, repeat]))
    return bytes(body)


def encode_vgl6_job(
    rows: list[list[int]],
    *,
    page_width: int,
    page_height: int,
    printable_width: int,
    printable_height: int,
    offset_x: int = 0,
    offset_y: int = 0,
    copies: int = 1,
    job_name: str = "HA",
    part_name: str = "M21",
    cut_end_of_label: bool = True,
) -> bytes:
    """Build a one-page VGL6 job from 1-bit rows (1=black)."""
    if not rows:
        raise ValueError("Cannot encode an empty image")
    copies = max(1, min(copies, 99))
    job_name_bytes = job_name.encode("ascii", "replace")[:20]
    part_bytes = part_name.encode("ascii", "replace")[:10]
    page_num = b"1"

    commands = bytearray()
    commands.extend(_stx(0x61))
    commands.extend(_stx(0x70, _ascii_signed3(0)))
    commands.extend(_stx(0x6F, _ascii_signed3(0)))
    commands.extend(_stx(0x4F, _ascii_signed3(0)))
    commands.extend(_stx(0x62, _ascii_signed3(0)))
    commands.extend(_stx(0x41))
    commands.extend(_stx(0x61))
    commands.extend(_stx(0x51))
    commands.extend(_stx_k(0x0C, _ascii_u4(page_width) + _ascii_u4(page_height)))
    commands.extend(
        _stx_k(0x0D, _ascii_u4(printable_width) + _ascii_u4(printable_height))
    )
    commands.extend(_stx_k(0x0E, _ascii_u4(offset_x) + _ascii_u4(offset_y)))
    commands.extend(_stx_k(0x09, part_bytes + b"\r"))
    commands.extend(_stx(0x61))
    commands.extend(_stx(0x4D, bytes([0x01 if cut_end_of_label else 0x00])))
    commands.extend(_stx(0x57, b"\x01"))
    commands.extend(_stx(0x44, _ascii_signed3(1)))
    commands.extend(_stx(0x43, _ascii_signed3(copies)))
    job_name_index = len(commands)
    commands.extend(_stx_k(0x0A, job_name_bytes + b"\r"))
    commands.extend(_stx_k(0x0B))
    commands.extend(_stx(0x61))
    commands.extend(_stx(0x61))
    commands.extend(_stx(0x49, b"IBUlbl" + page_num + b"\r"))
    commands.extend(b"X\x00\x00")
    commands.extend(b"Y\x00\x00")
    commands.extend(_row_commands(rows))
    commands.extend(b"\xff\xff\r")
    commands.extend(_stx(0x41))
    commands.extend(_stx(0x47))

    # page_count + payload_size + job_name_offset + command stream
    payload = struct.pack("<I", 4 + job_name_index) + bytes(commands)
    header = struct.pack("<II", 1, len(payload))
    return header + payload


def inches_to_dots(inches: float) -> int:
    """Convert inches to 203 dpi dots."""
    return max(1, round(inches * DPI))
