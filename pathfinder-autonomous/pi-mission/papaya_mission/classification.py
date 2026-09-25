"""Maps a camera-classified type + confidence to a permanent/temporary
obstacle status. See design spec: Mission Flow -- Detection (the type
heuristic: barrel/post/fence -> permanent-candidate; chair/vehicle ->
temporary) and Testing -- Malformed/low-confidence classification.
"""
from __future__ import annotations

from typing import Literal

LOW_CONFIDENCE_THRESHOLD = 0.5

_PERMANENT_TYPES = {"barrel", "utility_pole", "fence_post"}


def classify_permanence(
    classified_type: str, confidence: float
) -> Literal["temporary", "permanent-pending"]:
    """A low-confidence classification never gets promoted to
    permanent-pending, regardless of type match -- a wrong permanent tag
    pollutes the shared map more than a wrong temporary tag, which
    simply isn't carried forward. Anything not in the known permanent
    set (recognized temporary types and unrecognized/novel ones alike)
    defaults to temporary.
    """
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return "temporary"
    if classified_type in _PERMANENT_TYPES:
        return "permanent-pending"
    return "temporary"
