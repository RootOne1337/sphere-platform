import numpy as np
import pytest

from scripts.pilot.route_replay_lighting import (
    DETAIL_LOSS_PROFILES,
    LIGHTING_PROFILES,
    MAX_FRAME_PIXELS,
    apply_lighting,
)


@pytest.mark.parametrize("profile", LIGHTING_PROFILES)
def test_lighting_keeps_source_bytes_and_frame_layout(profile):
    source = np.arange(24 * 48 * 3, dtype=np.uint8).reshape(24, 48, 3)[:, ::2]
    snapshot = source.copy()
    source.setflags(write=False)
    output = apply_lighting(source, profile, seed=8)
    assert output.dtype == np.uint8 and output.shape == source.shape
    assert output.flags.c_contiguous and not np.shares_memory(output, source)
    np.testing.assert_array_equal(source, snapshot)
    np.testing.assert_array_equal(output, apply_lighting(source, profile, seed=8))
    assert np.array_equal(output, source) == (profile == "original")


@pytest.mark.parametrize("profile", tuple(p for p in LIGHTING_PROFILES if p not in DETAIL_LOSS_PROFILES))
def test_visible_detail_profiles_do_not_move_or_smear_local_image_structure(profile):
    original = np.full((60, 96, 3), 32, dtype=np.uint8)
    with_marker = original.copy()
    with_marker[10:25, 35:50, 1] = 80
    plain = apply_lighting(original, profile, seed=3)
    changed = apply_lighting(with_marker, profile, seed=3)
    np.testing.assert_array_equal(changed[:, :, (0, 2)], plain[:, :, (0, 2)])
    expected = np.zeros(original.shape[:2], dtype=bool)
    expected[10:25, 35:50] = True
    np.testing.assert_array_equal(changed[:, :, 1] > plain[:, :, 1], expected)


@pytest.mark.parametrize("profile", ["warm_shadow", "glare"])
def test_spatial_pattern_is_seeded_and_varies_across_the_frame(profile):
    source = np.full((60, 96, 3), 64, dtype=np.uint8)
    first = apply_lighting(source, profile, seed=1)
    second = apply_lighting(source, profile, seed=2)
    assert np.ptp(first[:, :, 1]) > 20
    assert not np.array_equal(first, second)


def test_tone_profile_direction_and_explicit_detail_loss():
    neutral = np.full((2, 2, 3), 64, dtype=np.uint8)
    assert apply_lighting(neutral, "daylight").mean() > neutral.mean()
    assert apply_lighting(neutral, "cool_twilight").mean() < neutral.mean()
    ramp = np.arange(256, dtype=np.uint8)[None, :, None].repeat(3, axis=2)
    assert (apply_lighting(ramp, "overexposed") == 255).mean() > 0.9


@pytest.mark.parametrize(
    ("source", "profile", "seed", "error"),
    [
        (np.zeros((1, 1, 3), dtype=np.float32), "original", 0, "frame"),
        (np.zeros((0, 1, 3), dtype=np.uint8), "original", 0, "frame"),
        (np.zeros((1, 1, 4), dtype=np.uint8), "original", 0, "frame"),
        (np.broadcast_to(np.zeros(3, dtype=np.uint8), (1, MAX_FRAME_PIXELS + 1, 3)), "original", 0, "frame"),
        (np.zeros((1, 1, 3), dtype=np.uint8), "unregistered", 0, "profile"),
        (np.zeros((1, 1, 3), dtype=np.uint8), "daylight", True, "seed"),
        (np.zeros((1, 1, 3), dtype=np.uint8), "daylight", -1, "seed"),
    ],
)
def test_invalid_inputs_fail_before_building_a_variant(source, profile, seed, error):
    with pytest.raises(ValueError, match=f"^route_lighting_{error}$"):
        apply_lighting(source, profile, seed=seed)
