from __future__ import annotations

from brady_m211.render import fit_canvas, render_text


def test_fit_canvas_die_cut_and_continuous() -> None:
    width, height = fit_canvas(printable_width=128, printable_height=50)
    assert width == 128
    assert height == 50
    width, height = fit_canvas(
        printable_width=None, printable_height=0, length_in=2.0
    )
    assert width == 128
    assert height == 406


def test_render_text_rows() -> None:
    rows = render_text(
        "HI",
        printable_width=64,
        printable_height=32,
    )
    assert len(rows) == 32
    assert len(rows[0]) == 64
    assert any(pixel for row in rows for pixel in row)
