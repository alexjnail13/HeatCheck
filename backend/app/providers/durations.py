"""
Duration parsing shared by every provider.

The NBA reports elapsed/remaining time in at least three shapes depending on
which endpoint you ask:

    "PT32M41.00S"   ISO-8601      cdn.nba.com live feeds, PlayByPlayV3 clock
    "32:41"         MM:SS         BoxScoreTraditionalV3 minutes
    "32"            bare minutes  some older/aggregate endpoints

All three mean the same thing, so they all parse to whole seconds here rather
than each provider module growing its own copy.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_ISO_DURATION = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>[\d.]+)S)?$",
    re.IGNORECASE,
)
_CLOCK = re.compile(r"^(?P<minutes>\d+):(?P<seconds>[\d.]+)$")
_BARE = re.compile(r"^(?P<minutes>\d+(?:\.\d+)?)$")


def parse_duration_to_seconds(value: str | int | float | None) -> int | None:
    """
    Parse a duration into whole seconds.

    Returns None for absent, blank or unparseable input — never 0. The caller
    needs "did not play" (None) and "played zero seconds" (0) to stay distinct,
    which is why player_game_stats.seconds_played is nullable.

    >>> parse_duration_to_seconds("PT32M41.00S")
    1961
    >>> parse_duration_to_seconds("32:41")
    1961
    >>> parse_duration_to_seconds("32")
    1920
    >>> parse_duration_to_seconds("") is None
    True
    """
    if value is None:
        return None

    # Numeric input is already minutes (some pandas columns arrive as floats).
    if isinstance(value, (int, float)):
        return int(round(float(value) * 60))

    text = str(value).strip()
    if not text:
        return None

    match = _ISO_DURATION.match(text)
    if match and any(match.groupdict().values()):
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = float(match.group("seconds") or 0)
        return int(round(hours * 3600 + minutes * 60 + seconds))

    match = _CLOCK.match(text)
    if match:
        return int(round(int(match.group("minutes")) * 60 + float(match.group("seconds"))))

    match = _BARE.match(text)
    if match:
        return int(round(float(match.group("minutes")) * 60))

    logger.warning("Unparseable duration %r — treating as unknown", value)
    return None
