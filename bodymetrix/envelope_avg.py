"""Rolling envelope average — BodyView-style multi-shot while SEND is held."""

from __future__ import annotations

import numpy as np

# Rolling tick frames (each tick already averages ms-rate wand shots).
MAX_AVERAGE_SAMPLES = 8
# USB drain per server tick — wand fires A-scans every few ms while SEND held.
TICK_DRAIN_MS = 220
# UI poll interval — server tick should finish within one poll period.
TICK_POLL_MS = 400
# Tick misses before we treat SEND as released.
MISS_TICKS_TO_CLEAR = 3


def average_envelopes(envs: list[np.ndarray]) -> np.ndarray | None:
    if not envs:
        return None
    length = min(len(e) for e in envs)
    if length < 32:
        return None
    stack = np.stack([e[:length] for e in envs], axis=0)
    return np.mean(stack, axis=0)
