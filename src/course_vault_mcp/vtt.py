from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Iterable


TIMING_RE = re.compile(
    r"^(?P<start>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})(?:\s+.*)?$"
)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    start_text: str
    end_text: str
    text: str


def timestamp_to_seconds(value: str) -> float:
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError("invalid VTT timestamp")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def normalize_caption_text(lines: Iterable[str]) -> str:
    joined = " ".join(line.strip() for line in lines if line.strip())
    without_tags = TAG_RE.sub("", joined)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def parse_vtt(text: str) -> list[Cue]:
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("WEBVTT"):
        raise ValueError("caption does not begin with WEBVTT")

    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", normalized):
        lines = block.split("\n")
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        match = TIMING_RE.match(lines[timing_index].strip())
        if not match:
            continue
        cue_text = normalize_caption_text(lines[timing_index + 1 :])
        if not cue_text:
            continue
        start_text = match.group("start").replace(",", ".")
        end_text = match.group("end").replace(",", ".")
        cues.append(
            Cue(
                start=timestamp_to_seconds(start_text),
                end=timestamp_to_seconds(end_text),
                start_text=start_text,
                end_text=end_text,
                text=cue_text,
            )
        )
    if not cues:
        raise ValueError("caption contains no valid cues")
    return cues


def segment_cues(
    cues: list[Cue], target_seconds: float = 150.0, max_characters: int = 6000
) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    current: list[Cue] = []
    character_count = 0

    def flush() -> None:
        nonlocal current, character_count
        if not current:
            return
        segments.append(
            {
                "start": current[0].start_text,
                "end": current[-1].end_text,
                "cue_count": len(current),
                "text": " ".join(cue.text for cue in current),
            }
        )
        current = []
        character_count = 0

    for cue in cues:
        would_exceed_time = bool(current) and cue.end - current[0].start > target_seconds
        would_exceed_chars = bool(current) and character_count + len(cue.text) > max_characters
        if would_exceed_time or would_exceed_chars:
            flush()
        current.append(cue)
        character_count += len(cue.text) + 1
    flush()
    return segments
