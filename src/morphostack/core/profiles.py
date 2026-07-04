"""Analysis profile definitions."""

from __future__ import annotations

from typing import Literal

AnalysisProfile = Literal["vesicle", "rbc"]

DEFAULT_PROFILE: AnalysisProfile = "vesicle"
PROFILE_CHOICES: tuple[AnalysisProfile, ...] = ("vesicle", "rbc")


def normalize_profile(profile: str | None) -> AnalysisProfile:
    if profile is None:
        return DEFAULT_PROFILE
    value = profile.strip().lower()
    if value not in PROFILE_CHOICES:
        choices = ", ".join(PROFILE_CHOICES)
        raise ValueError(f"analysis profile must be one of: {choices}")
    return value  # type: ignore[return-value]
