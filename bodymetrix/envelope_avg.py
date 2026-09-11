"""Rolling envelope average — BodyView-style multi-shot while SEND is held."""

from __future__ import annotations

import numpy as np

# Samples collected while the operator moves the wand in a small circle.
MAX_AVERAGE_SAMPLES = 10
# Tick misses before we treat SEND as released.
MISS_TICKS_TO_CLEAR = 4


def average_envelopes(envs: list[np.ndarray]) -> np.ndarray | None:
    if not envs:
        return None
    length = min(len(e) for e in envs)
    if length < 32:
        return None
    stack = np.stack([e[:length] for e in envs], axis=0)
    return np.mean(stack, axis=0)
