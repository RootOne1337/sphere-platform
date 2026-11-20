import math
import struct

import pytest

from scripts.pilot.world_map_lab.check_journey_rgb import (
    RECOVERY_PANS,
    RECOVERY_START,
    recovery_camera,
    scan_due,
)
from scripts.pilot.world_map_lab.prepare_boot_probe import language_table
from scripts.pilot.world_map_lab.record_native_journey import validate


def test_wide_search_needs_a_second_distinct_view():
    for index, pan in enumerate(RECOVERY_PANS):
        first = RECOVERY_START + 2 * index
        assert scan_due(first) and not scan_due(first + 1)
        assert recovery_camera(first) == pytest.approx(math.radians(pan))
        assert recovery_camera(first + 1) - recovery_camera(first) == pytest.approx(0.18)


def test_language_probe_points_to_sorted_keys_and_terminated_text():
    data = language_table()
    version, alphabet, tag, size, main, offset = struct.unpack_from("<HH4sI8sI", data)
    assert (version, alphabet, tag, size, main.rstrip(b"\0"), offset) == (
        4,
        8,
        b"TABL",
        12,
        b"MAIN",
        24,
    )
    tag, key_bytes = struct.unpack_from("<4sI", data, offset)
    assert tag == b"TKEY"
    keys = list(struct.iter_unpack("<II", data[offset + 8 : offset + 8 + key_bytes]))
    text_at = offset + 8 + key_bytes
    tag, size = struct.unpack_from("<4sI", data, text_at)
    strings = data[text_at + 8 :]
    assert tag == b"TDAT" and len(strings) == size
    assert [k for i, k in keys] == sorted(k for i, k in keys)
    assert {strings[i:].split(b"\0", 1)[0] for i, k in keys} == {
        b"Start",
        b"Quit",
        b"Test data unavailable",
    }


def observations():
    lines = []
    for i in range(12):
        phase = {0: "start", 3: "boarded", 8: "parked_and_exited", 11: "goal_on_foot"}.get(i)
        if phase:
            lines.append("sphere_scenario event=" + phase)
        lines.append(
            f"sphere_truth t={200 * i} pos={i},0,0 mounted={'true' if 3 <= i < 8 else 'false'} health=99.0 head=true"
        )
    return [dict(line=line) for line in lines]


def test_native_journey_requires_motorcycle_and_both_walks():
    assert validate(observations()) == [2, 4, 3]
    for before, after in (
        ("parked_and_exited", "unplanned_dismount"),
        ("head=true", "head=false"),
        ("event=boarded", "event=irrelevant"),
        ("t=800", "t=8000"),
        ("goal_on_foot", "stalled"),
    ):
        events = observations()
        rec = next(r for r in events if before in r["line"])
        rec["line"] = rec["line"].replace(before, after)
        with pytest.raises(ValueError):
            validate(events)
    with pytest.raises(ValueError):
        validate(observations()[:-1])
