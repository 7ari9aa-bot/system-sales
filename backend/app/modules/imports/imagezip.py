"""Read pictures out of a merchant's .zip, safely.

The archive is hostile input. Everything is decided from the zip's central directory (names and
declared sizes) BEFORE any byte is inflated, and the real inflated size is enforced again while
reading, because the declared size is only a claim. Pure functions over bytes: no database, no
network, no storage.

What is refused, and why:

* **Path tricks** (``../x.jpg``, ``/etc/x.jpg``, ``C:\\x.jpg``, NUL bytes): a name is only ever
  used as a lookup key, never as a path, but a hostile name is refused at the door anyway so it
  can never become one by accident later.
* **Zip bombs**: too many entries, one entry that inflates past the per-picture cap, a total
  that inflates past the archive cap, and any entry whose compression ratio is absurd.
* **Encrypted entries**: they cannot be read, so they are refused with a reason rather than
  failing later.
* **Symlinks**: an entry that is a link is not a picture.
* **Folders, ``__MACOSX/`` resource forks, ``.DS_Store``, ``Thumbs.db``**: skipped silently; they
  are what Finder and Explorer add, not something the merchant meant.

Pictures are matched by file name, case-insensitively and ignoring the folder they sit in, so
``photos/Tee-Red.JPG`` answers a row that says ``tee-red.jpg``. Two different pictures that
collapse to the same name make that name ambiguous and it is refused rather than guessed.
"""

from __future__ import annotations

import io
import stat
import unicodedata
import zipfile
from dataclasses import dataclass, field

from app.core.errors import ValidationError

MAX_ZIP_BYTES = 200 * 1024 * 1024  # the archive itself (it is stored, not held in memory)
MAX_ENTRIES = 5_000  # pictures in one archive; the sheet is capped well below the row ceiling
MAX_PICTURE_BYTES = 10 * 1024 * 1024  # the same ceiling as a picture uploaded by hand
MAX_TOTAL_UNCOMPRESSED = 1024 * 1024 * 1024  # all pictures together, once inflated
MAX_RATIO = 200  # inflated / stored; real photos are ~1, a bomb is thousands
_RATIO_FLOOR = 64 * 1024  # a tiny file can look extreme (a blank PNG); only judge bigger ones

PICTURE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
_NOISE_DIRS = ("__macosx/",)
_NOISE_FILES = (".ds_store", "thumbs.db", "desktop.ini")


@dataclass(frozen=True, slots=True)
class Entry:
    key: str  # the lookup key: base name, NFKC, casefolded
    name: str  # the entry's full name inside the archive (what ``read_entry`` takes)
    size: int  # declared inflated size


@dataclass(slots=True)
class Catalog:
    """What the archive holds, decided without inflating anything."""

    entries: dict[str, Entry] = field(default_factory=dict)  # key -> entry
    ambiguous: set[str] = field(default_factory=set)  # keys two different pictures claim
    refused: dict[str, str] = field(default_factory=dict)  # entry name -> reason

    def find(self, wanted: str) -> Entry | None:
        return self.entries.get(lookup_key(wanted))


def lookup_key(name: str) -> str:
    """The base name, NFKC-normalised and casefolded: how a row's name meets an entry."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return unicodedata.normalize("NFKC", base).strip().casefold()


def _unsafe_name(name: str) -> str | None:
    """Why this entry name cannot be trusted, or None."""
    if "\x00" in name or any(ord(c) < 32 for c in name):
        return "control characters in the name"
    flat = name.replace("\\", "/")
    if flat.startswith("/") or (len(flat) > 1 and flat[1] == ":"):
        return "absolute path"
    if ".." in flat.split("/"):
        return "path leaves the archive"
    return None


def _is_noise(name: str) -> bool:
    low = name.replace("\\", "/").casefold()
    base = low.rsplit("/", 1)[-1]
    return low.endswith("/") or any(low.startswith(d) for d in _NOISE_DIRS) or base in _NOISE_FILES


def open_archive(data: bytes) -> zipfile.ZipFile:
    if len(data) > MAX_ZIP_BYTES:
        raise ValidationError("the pictures archive is too large")
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationError("this file is not a valid .zip archive") from exc


def catalog_of(data: bytes) -> Catalog:
    """Read the central directory only. Raises when the archive as a whole is unacceptable."""
    zf = open_archive(data)
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValidationError(f"the archive holds more than {MAX_ENTRIES} files")
    declared_total = sum(i.file_size for i in infos)
    if declared_total > MAX_TOTAL_UNCOMPRESSED:
        raise ValidationError("the pictures are too large once unpacked")

    out = Catalog()
    for info in infos:
        name = info.filename
        if _is_noise(name):
            continue
        reason = _unsafe_name(name)
        if reason is None and info.flag_bits & 0x1:
            reason = "encrypted"
        if reason is None and stat.S_ISLNK(info.external_attr >> 16):
            reason = "symbolic link"
        if reason is None and not name.casefold().endswith(PICTURE_EXTENSIONS):
            reason = "not a picture file name"
        if reason is None and info.file_size > MAX_PICTURE_BYTES:
            reason = "picture is larger than 10 MB"
        if reason is None and (
            info.file_size > _RATIO_FLOOR
            and info.file_size > MAX_RATIO * max(info.compress_size, 1)
        ):
            reason = "compression ratio is not that of a picture"
        if reason is not None:
            out.refused[name] = reason
            continue
        key = lookup_key(name)
        if key in out.entries or key in out.ambiguous:
            out.ambiguous.add(key)
            out.entries.pop(key, None)
            continue
        out.entries[key] = Entry(key=key, name=name, size=info.file_size)
    return out


def read_entry(data: bytes, entry: Entry) -> bytes:
    """Inflate ONE entry, never trusting its declared size.

    The read stops one byte past the cap, so a header that lies about its size cannot make a
    worker inflate gigabytes: the loop is bounded by what is actually produced.
    """
    zf = open_archive(data)
    try:
        with zf.open(entry.name) as fh:
            body = fh.read(MAX_PICTURE_BYTES + 1)
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValidationError("this picture could not be read from the archive") from exc
    if len(body) > MAX_PICTURE_BYTES:
        raise ValidationError("picture is larger than 10 MB")
    return body
