"""Plausible subcutaneous fat thickness range (mm) for BX2000 site readings."""

# ~3 mm is typical skin (epidermis + dermis) — first echo, not fat depth.
SKIN_THICKNESS_MM = 3.0

# Hard floor: reject USB decode garbage (e.g. 1.7 mm misreads). Matches skin depth.
MIN_PLAUSIBLE_MM = SKIN_THICKNESS_MM

# ~2 inches — practical ceiling for thigh/waist site fat thickness.
MAX_PLAUSIBLE_MM = 50.0

MIN_PLAUSIBLE_TENTHS = int(MIN_PLAUSIBLE_MM * 10)
MAX_PLAUSIBLE_TENTHS = int(MAX_PLAUSIBLE_MM * 10)

# Readings in this band are often the skin boundary, not fat–muscle.
SKIN_BAND_MM = 0.5


def is_plausible_mm(mm: float) -> bool:
    return MIN_PLAUSIBLE_MM <= mm <= MAX_PLAUSIBLE_MM


def is_likely_skin_reading(mm: float) -> bool:
    """True when depth is at the skin echo, not subcutaneous fat."""
    return mm <= SKIN_THICKNESS_MM + SKIN_BAND_MM
