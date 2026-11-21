"""Deterministic screen-space lighting stress for offline route replay."""

from __future__ import annotations

import numpy as np

LIGHTING_POLICY = "screen_space_photometric_v2"
MAX_FRAME_PIXELS = 1920 * 1080
# Gamma, RGB white balance, and black level on the displayed image.
_TONE_PROFILES = {
    "overcast": (0.80, (1.00, 1.00, 1.01), 0.025),
    "daylight": (0.57, (1.04, 1.00, 0.91), 0.045),
    "warm_shadow": (0.65, (1.04, 0.99, 0.87), 0.035),
    "cool_twilight": (1.38, (0.77, 0.91, 1.04), 0.012),
    "glare": (0.82, (1.01, 1.00, 0.98), 0.023),
    "overexposed": (0.51, (1.0, 1.0, 1.0), 0.04),
    "low_key": (1.72, (0.90, 0.96, 1.02), 0.0),
    "side_sun": (0.51, (1.07, 1.00, 0.86), 0.030),
    "haze": (0.72, (0.97, 1.00, 1.04), 0.14),
}
LIGHTING_PROFILES = ("original", *_TONE_PROFILES)
DETAIL_LOSS_PROFILES = frozenset({"overexposed"})


def _spatial_field(profile, height, width, seed):
    rng = np.random.default_rng(seed)
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    if profile in {"warm_shadow", "side_sun"}:
        boundary = rng.uniform(0.36, 0.61) + rng.uniform(-0.45, 0.45) * (y - 0.5)
        shadow = x - boundary
        shadow *= 18.0
        np.tanh(shadow, out=shadow)
        strength = 0.35 if profile == "side_sun" else 0.24
        shadow *= strength
        shadow += 1.0 - strength
        if profile == "side_sun":
            shadow = shadow[:, ::-1]
        return shadow
    center_x, center_y = rng.uniform(0.24, 0.76), rng.uniform(0.15, 0.40)
    radius = np.square((x - center_x) / 0.23) + np.square((y - center_y) / 0.32)
    radius *= -0.5
    np.exp(radius, out=radius)
    radius *= 0.56
    return radius


def apply_lighting(rgb: np.ndarray, profile: str, *, seed: int = 0) -> np.ndarray:
    """Keep the source pixel grid and alter RGB only, leaving the input intact.

    A replay should hold the seed fixed. The resulting soft shadow or flare is
    coherent in screen space. It does not model game-world lights or visibility.
    """
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or not 0 < rgb.shape[0] * rgb.shape[1] <= MAX_FRAME_PIXELS
    ):
        raise ValueError("route_lighting_frame")
    if not isinstance(profile, str) or profile not in LIGHTING_PROFILES:
        raise ValueError("route_lighting_profile")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("route_lighting_seed")
    if profile == "original":
        return rgb.copy(order="C")

    gamma, balance, black_level = _TONE_PROFILES[profile]
    levels = np.linspace(0.0, 1.0, 256, dtype=np.float32) ** gamma
    field = (
        _spatial_field(profile, rgb.shape[0], rgb.shape[1], seed)
        if profile in {"warm_shadow", "side_sun", "glare"} else None
    )
    result = np.empty(rgb.shape, dtype=np.uint8)
    for channel, gain in enumerate(balance):
        tone = (levels * gain * (0.96 - black_level) + black_level) * 255.0
        values = tone[rgb[:, :, channel]]
        if profile in {"warm_shadow", "side_sun"}:
            values *= field
        elif profile == "glare":
            # Veiling light lifts dark pixels more strongly near the flare.
            values += field * (255.0 - values)
        elif profile == "overexposed":
            # Deliberately destroy most contrast through highlight clipping.
            values *= 1.9
            values += 195.0
        np.clip(values, 0.0, 255.0, out=values)
        np.rint(values, out=values)
        result[:, :, channel] = values
    return result


def photometric_summary(rgb: np.ndarray) -> dict:
    """Measure the delivered 8-bit RGB, including the impact of JPEG."""
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    p05, p95 = np.percentile(luma, [5, 95])
    return dict(lumaMean=float(luma.mean()), lumaP05=float(p05), lumaP95=float(p95),
                blackChannelFraction=float((rgb == 0).mean()),
                whiteChannelFraction=float((rgb == 255).mean()))
