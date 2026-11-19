"""What Facebook accepts as a Reel or a Story, decided from the file's own bytes.

Meta's rules ("Reels Publishing API", "Facebook Stories API"), all checked BEFORE a byte is
stored or sent, so a file Facebook would refuse fails while the agent can still pick another:

* a Reel is an mp4 of 3 to 90 seconds, 9:16, at least 540 x 960;
* a video Story is the same but at most 60 seconds;
* a photo Story is a jpeg/png/gif/bmp/tiff of at most 10 MB.

The size and length come from the mp4's own header (its `moov` box), never from the file name
or the type the browser claimed. No video library is needed: an mp4 is a tree of boxes and only
three of them matter here, so a short reader keeps the backend free of a native dependency.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MB = 1024 * 1024

REEL_MIN_SECONDS = 3
REEL_MAX_SECONDS = 90
STORY_MAX_SECONDS = 60
MIN_WIDTH, MIN_HEIGHT = 540, 960
#: 9:16 with a little room for the rounding a phone's encoder does (1080x1920 is exact).
RATIO = 9 / 16
RATIO_TOLERANCE = 0.02
#: Meta states no byte limit for a Reel; this is OUR ceiling so one request cannot fill memory.
MAX_VIDEO_BYTES = 200 * MB
MAX_STORY_PHOTO_BYTES = 10 * MB
#: A Reel the app publishes: Meta's own rate limit on POST /{page}/video_reels.
REELS_PER_DAY = 30
#: A scheduled Reel goes live between 10 minutes and 29 days from now.
REEL_SCHEDULE_MIN_SECONDS = 10 * 60
REEL_SCHEDULE_MAX_SECONDS = 29 * 24 * 3600


class FacebookVideoError(ValueError):
    """The file cannot be a Reel or a Story; the message says why, in words for the agent."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int
    height: int
    seconds: float
    size: int


# ------------------------------------------------------------------ reading an mp4


def _boxes(data: bytes, start: int, end: int):
    """(type, body_start, body_end) of each box between `start` and `end`."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:  # a 64-bit size follows the type
            if pos + 16 > end:
                return
            (size,) = struct.unpack_from(">Q", data, pos + 8)
            header = 16
        elif size == 0:  # the box runs to the end of its parent
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _find(data: bytes, start: int, end: int, kind: bytes):
    for k, a, b in _boxes(data, start, end):
        if k == kind:
            return a, b
    return None


def _duration(data: bytes, a: int, b: int) -> float | None:
    """Seconds from the movie header box (`mvhd`)."""
    if b - a < 20:
        return None
    version = data[a]
    if version == 1:
        if b - a < 32:
            return None
        timescale, duration = struct.unpack_from(">IQ", data, a + 20)
    else:
        timescale, duration = struct.unpack_from(">II", data, a + 12)
    return duration / timescale if timescale else None


def _track_size(data: bytes, a: int, b: int) -> tuple[int, int] | None:
    """Width and height of a track from its header (`tkhd`), as shown (16.16 fixed point)."""
    version = data[a]
    off = a + (88 if version == 1 else 76)
    if off + 8 > b:
        return None
    w, h = struct.unpack_from(">II", data, off)
    return w >> 16, h >> 16


def _rotation_swaps(data: bytes, a: int, b: int) -> bool:
    """True when the track is turned a quarter (a phone's portrait video is stored sideways).

    The 3x3 transform matrix of the track header decides it: the identity (and a plain flip)
    leaves width and height as they are; a quarter turn puts the shear terms where the scale was.
    """
    version = data[a]
    # version and flags, times, ids and duration, 8 reserved, layer, group, volume, 2 reserved
    base = a + (
        4 + 8 + 8 + 4 + 4 + 8 + 8 + 2 + 2 + 2 + 2
        if version == 1
        else 4 + 4 + 4 + 4 + 4 + 4 + 8 + 2 + 2 + 2 + 2
    )
    if base + 36 > b:
        return False
    m = struct.unpack_from(">9i", data, base)
    return m[0] == 0 and m[4] == 0 and (m[1] != 0 or m[3] != 0)


def read_mp4(data: bytes) -> VideoInfo:
    """The picture size and length of an mp4, or FacebookVideoError when it is not one."""
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise FacebookVideoError("video_format", "Facebook takes only mp4 video")
    moov = _find(data, 0, len(data), b"moov")
    if moov is None:
        raise FacebookVideoError(
            "video_unreadable", "the video has no header, so it may be cut short or damaged"
        )
    mvhd = _find(data, *moov, b"mvhd")
    seconds = _duration(data, *mvhd) if mvhd else None
    if seconds is None:
        raise FacebookVideoError("video_unreadable", "the video's length cannot be read")
    size: tuple[int, int] | None = None
    for kind, a, b in _boxes(data, *moov):
        if kind != b"trak":
            continue
        mdia = _find(data, a, b, b"mdia")
        hdlr = _find(data, *mdia, b"hdlr") if mdia else None
        # the picture track, not the sound: its handler type reads "vide"
        if not hdlr or data[hdlr[0] + 8 : hdlr[0] + 12] != b"vide":
            continue
        tkhd = _find(data, a, b, b"tkhd")
        if tkhd:
            size = _track_size(data, *tkhd)
            if size and _rotation_swaps(data, *tkhd):
                size = (size[1], size[0])
            break
    if not size or not size[0] or not size[1]:
        raise FacebookVideoError("video_unreadable", "the video has no picture")
    return VideoInfo(width=size[0], height=size[1], seconds=seconds, size=len(data))


# ------------------------------------------------------------------ the rules


def _check_video(data: bytes, *, max_seconds: int, what: str) -> VideoInfo:
    if not data:
        raise FacebookVideoError("video_empty", "the video is empty")
    if len(data) > MAX_VIDEO_BYTES:
        raise FacebookVideoError(
            "video_size", f"the video is larger than {MAX_VIDEO_BYTES // MB} MB"
        )
    info = read_mp4(data)
    if info.width < MIN_WIDTH or info.height < MIN_HEIGHT:
        raise FacebookVideoError(
            "video_resolution",
            f"a {what} must be at least {MIN_WIDTH} x {MIN_HEIGHT}; this one is "
            f"{info.width} x {info.height}",
        )
    if abs(info.width / info.height - RATIO) > RATIO_TOLERANCE:
        raise FacebookVideoError(
            "video_ratio",
            f"a {what} must be tall (9:16); this one is {info.width} x {info.height}",
        )
    if info.seconds < REEL_MIN_SECONDS:
        raise FacebookVideoError(
            "video_short", f"a {what} is at least {REEL_MIN_SECONDS} seconds; this one is "
            f"{info.seconds:.1f}"
        )  # fmt: skip
    if info.seconds > max_seconds:
        raise FacebookVideoError(
            "video_long",
            f"a {what} is at most {max_seconds} seconds; this one is {info.seconds:.0f}",
        )
    return info


def check_reel(data: bytes) -> VideoInfo:
    return _check_video(data, max_seconds=REEL_MAX_SECONDS, what="Reel")


def check_video_story(data: bytes) -> VideoInfo:
    return _check_video(data, max_seconds=STORY_MAX_SECONDS, what="Story")


# A photo Story. Meta lists jpeg, bmp, png, gif and tiff.
_PHOTO_KINDS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def check_story_photo(data: bytes) -> str:
    """The type of a photo Story, or FacebookVideoError naming why Facebook would refuse it."""
    if not data:
        raise FacebookVideoError("photo_empty", "the picture is empty")
    if len(data) > MAX_STORY_PHOTO_BYTES:
        raise FacebookVideoError("photo_size", "a Story picture is at most 10 MB")
    for magic, kind in _PHOTO_KINDS:
        if data.startswith(magic):
            return kind
    raise FacebookVideoError(
        "photo_format", "a Story picture must be a JPEG, PNG, GIF, BMP or TIFF"
    )
