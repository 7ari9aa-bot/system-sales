"""The pictures archive is hostile input: every refusal is decided before anything is inflated."""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from app.core.errors import ValidationError
from app.modules.imports import imagezip as z

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _zip(files: dict[str, bytes], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def test_a_folder_of_pictures_is_matched_by_name_ignoring_case_and_folder():
    cat = z.catalog_of(_zip({"photos/Tee-Red.JPG": PNG, "blue.png": PNG}))
    assert cat.find("tee-red.jpg").name == "photos/Tee-Red.JPG"
    assert cat.find("BLUE.PNG") is not None
    assert cat.find("missing.png") is None
    assert cat.refused == {} and cat.ambiguous == set()


def test_arabic_names_match_across_unicode_forms():
    composed = "قميص-أحمر.jpg"
    cat = z.catalog_of(_zip({composed: PNG}))
    assert cat.find("قميص-أحمر.JPG") is not None


@pytest.mark.parametrize(
    "name",
    ["../evil.jpg", "a/../../evil.jpg", "/etc/evil.jpg", "C:/evil.jpg", "..\\evil.jpg"],
)
def test_names_that_walk_out_of_the_archive_are_refused(name):
    cat = z.catalog_of(_zip({name: PNG, "ok.jpg": PNG}))
    assert name in cat.refused
    assert cat.find("ok.jpg") is not None
    assert cat.find("evil.jpg") is None  # a refused name never becomes a match


def test_a_name_with_control_characters_is_refused():
    cat = z.catalog_of(_zip({"a\x01b.jpg": PNG}))
    assert list(cat.refused.values()) == ["control characters in the name"]


def test_only_picture_names_are_taken_and_the_rest_is_reported():
    cat = z.catalog_of(
        _zip({"a.jpg": PNG, "run.exe": b"MZ", "notes.txt": b"hi", "p.svg": b"<svg/>"})
    )
    assert set(cat.entries) == {"a.jpg"}
    assert set(cat.refused) == {"run.exe", "notes.txt", "p.svg"}


def test_what_finder_and_explorer_add_is_skipped_without_comment():
    cat = z.catalog_of(
        _zip({"__MACOSX/._a.jpg": b"x", ".DS_Store": b"x", "Thumbs.db": b"x", "a.jpg": PNG})
    )
    assert set(cat.entries) == {"a.jpg"} and cat.refused == {}


def test_two_different_pictures_with_one_name_make_it_ambiguous_not_a_guess():
    cat = z.catalog_of(_zip({"a/tee.jpg": PNG, "b/TEE.jpg": PNG + b"1"}))
    assert cat.find("tee.jpg") is None
    assert cat.ambiguous == {"tee.jpg"}


def test_a_symlink_entry_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.jpg")
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "/etc/passwd")
    cat = z.catalog_of(buf.getvalue())
    assert cat.refused == {"link.jpg": "symbolic link"}


def test_an_encrypted_entry_is_refused_instead_of_failing_later():
    raw = bytearray(_zip({"a.jpg": PNG}))
    # set the "encrypted" bit in both the local header and the central directory
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = raw.find(sig)
        flags = struct.unpack_from("<H", raw, i + off)[0] | 0x1
        struct.pack_into("<H", raw, i + off, flags)
    cat = z.catalog_of(bytes(raw))
    assert cat.refused == {"a.jpg": "encrypted"}


def test_a_compression_bomb_is_refused_from_the_directory_alone():
    bomb = _zip({"bomb.png": b"\x00" * (8 * 1024 * 1024)})  # 8 MB of zeros, a few KB stored
    assert len(bomb) < 20_000
    cat = z.catalog_of(bomb)
    assert cat.refused == {"bomb.png": "compression ratio is not that of a picture"}


def test_a_picture_over_the_cap_is_refused():
    big = _zip({"big.png": PNG + bytes(range(256)) * (z.MAX_PICTURE_BYTES // 256 + 1)})
    assert z.catalog_of(big).refused == {"big.png": "picture is larger than 10 MB"}


def test_too_many_entries_refuses_the_whole_archive(monkeypatch):
    monkeypatch.setattr(z, "MAX_ENTRIES", 3)
    with pytest.raises(ValidationError, match="more than 3 files"):
        z.catalog_of(_zip({f"{i}.jpg": PNG for i in range(4)}))


def test_a_total_that_inflates_too_far_refuses_the_whole_archive(monkeypatch):
    monkeypatch.setattr(z, "MAX_TOTAL_UNCOMPRESSED", 100)
    with pytest.raises(ValidationError, match="too large once unpacked"):
        z.catalog_of(_zip({"a.jpg": PNG, "b.jpg": PNG}, compression=zipfile.ZIP_STORED))


def test_something_that_is_not_a_zip_is_a_clear_error():
    with pytest.raises(ValidationError, match="not a valid .zip"):
        z.catalog_of(b"definitely not a zip")


def test_an_oversized_archive_is_refused_before_it_is_opened(monkeypatch):
    monkeypatch.setattr(z, "MAX_ZIP_BYTES", 10)
    with pytest.raises(ValidationError, match="too large"):
        z.catalog_of(b"x" * 11)


def test_reading_an_entry_returns_its_bytes():
    data = _zip({"d/a.png": PNG})
    entry = z.catalog_of(data).find("a.png")
    assert z.read_entry(data, entry) == PNG


def test_a_header_that_lies_about_its_size_cannot_inflate_past_the_cap(monkeypatch):
    """The declared size is a claim. The read is bounded by what is actually produced."""
    monkeypatch.setattr(z, "MAX_PICTURE_BYTES", 1000)
    data = _zip({"a.png": b"\x00" * 50_000})
    liar = z.Entry(key="a.png", name="a.png", size=10)  # claims 10 bytes
    with pytest.raises(ValidationError, match="larger than 10 MB"):
        z.read_entry(data, liar)


def test_a_corrupt_entry_is_a_clear_error_not_a_crash():
    raw = bytearray(_zip({"a.png": PNG}, compression=zipfile.ZIP_STORED))
    i = raw.find(PNG)
    raw[i + 10] ^= 0xFF  # flip a byte of the stored body: the CRC no longer matches
    entry = z.catalog_of(bytes(raw)).find("a.png")
    with pytest.raises(ValidationError, match="could not be read"):
        z.read_entry(bytes(raw), entry)


def test_the_read_stops_at_the_cap_instead_of_inflating_the_whole_entry(monkeypatch):
    """Checking the size AFTER ``read()`` is too late: the bomb is already in memory by then.

    The result alone cannot tell the two apart (both raise), so count what the reader really
    asked the decompressor for.
    """
    monkeypatch.setattr(z, "MAX_PICTURE_BYTES", 1000)
    data = _zip({"a.png": b"\x00" * 5_000_000})
    produced: list[int] = []
    real_open = zipfile.ZipFile.open

    def spy(self, *a, **k):
        fh = real_open(self, *a, **k)
        real_read = fh.read

        def counted(n=-1):
            out = real_read(n)
            produced.append(len(out))
            return out

        fh.read = counted
        return fh

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)
    liar = z.Entry(key="a.png", name="a.png", size=10)
    with pytest.raises(ValidationError):
        z.read_entry(data, liar)
    assert produced and max(produced) <= 1001  # one byte past the cap, never the 5 MB


def test_a_name_two_pictures_claim_stays_ambiguous_even_with_a_third_claimant():
    cat = z.catalog_of(_zip({"a/x.jpg": PNG, "b/X.jpg": PNG + b"1", "c/x.JPG": PNG + b"2"}))
    assert cat.find("x.jpg") is None
    assert cat.ambiguous == {"x.jpg"}


def test_the_first_of_two_clashing_names_is_not_silently_the_winner():
    cat = z.catalog_of(_zip({"a/x.jpg": PNG, "b/X.jpg": PNG + b"1"}))
    assert "x.jpg" not in cat.entries
