"""Direct coverage for the shared on-disk serialization helpers.

Store roundtrips exercise these indirectly; diary (ADR-0001 Phase 2) will call
the same functions, so pin the wire format here before a second consumer lands.
"""

from pathlib import Path

from wikimem._serialize import atomic_write, meta_value, now_iso, parse_meta, render_meta


def test_parse_meta_happy_path():
    line = "<!-- wikimem: owner=user:xnne | source=conv_1 | ts=2026-07-10T03:00:00+00:00 -->"
    assert parse_meta(line) == {
        "owner": "user:xnne",
        "source": "conv_1",
        "ts": "2026-07-10T03:00:00+00:00",
    }


def test_parse_meta_rejects_non_meta_and_tolerates_junk_fields():
    assert parse_meta("## heading") is None
    assert parse_meta("not a comment") is None
    # missing value → dropped; empty key → dropped; good field kept
    parsed = parse_meta("<!-- wikimem: owner=ok | broken | =novalue | keep=yes -->")
    assert parsed == {"owner": "ok", "keep": "yes"}


def test_parse_meta_strips_surrounding_whitespace():
    line = "  <!-- wikimem: owner=a | source=b -->  \n"
    assert parse_meta(line) == {"owner": "a", "source": "b"}


def test_meta_value_escapes_field_separator():
    assert meta_value("a|b") == "a/b"
    assert meta_value("  padded  ") == "padded"


def test_render_meta_none_when_empty_or_whitespace():
    assert render_meta() is None
    assert render_meta(owner=None, source_conv=None, ts=None) is None
    # whitespace / empty collapse after meta_value; bare "|" escapes to "/" and is kept
    assert render_meta(owner="   ", source_conv="  ", ts="") is None


def test_render_meta_escapes_and_orders_fields():
    rendered = render_meta(
        owner="user|xnne",
        source_conv="conv|1",
        ts="2026-07-10T03:00:00+00:00",
    )
    assert rendered == (
        "<!-- wikimem: owner=user/xnne | source=conv/1 | ts=2026-07-10T03:00:00+00:00 -->"
    )


def test_render_parse_roundtrip():
    rendered = render_meta(owner="user:xnne", source_conv="c1", ts="2026-01-01T00:00:00+00:00")
    assert rendered is not None
    assert parse_meta(rendered) == {
        "owner": "user:xnne",
        "source": "c1",
        "ts": "2026-01-01T00:00:00+00:00",
    }


def test_now_iso_is_utc_second_precision():
    stamp = now_iso()
    # datetime.isoformat(timespec="seconds") with timezone.utc → ...+00:00, no fraction
    assert stamp.endswith("+00:00")
    assert "." not in stamp
    assert "T" in stamp


def test_atomic_write_nested_path_and_overwrite(tmp_path: Path):
    target = tmp_path / "diary" / "2026-07-21.md"
    atomic_write(target, "first\n")
    assert target.read_text(encoding="utf-8") == "first\n"
    atomic_write(target, "second\n")
    assert target.read_text(encoding="utf-8") == "second\n"
    # no leftover temps in the diary dir
    assert list(target.parent.glob("*.tmp")) == []
