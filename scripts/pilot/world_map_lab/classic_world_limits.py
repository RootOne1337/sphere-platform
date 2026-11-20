"""Size the original PC engine's adjustable pools from an imported world package."""

import math
from collections import Counter

CONFIG_NAME = "fastman92limitAdjuster_GTASA.ini"


def requirements(manifest, highest_model, ide, water, base_archives=0):
    sections = Counter()
    section = ""
    for raw in ide.read_text(encoding="utf-8-sig").splitlines():
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        if "," not in line:
            section = line.lower()
        else:
            sections[section] += 1
    water_faces = Counter()
    extent = max(
        (abs(v) for corner in manifest["exteriorBounds"] or () for v in corner[:2]), default=0
    )
    for raw in water.read_text(encoding="cp1252").splitlines():
        fields = raw.partition("#")[0].split()
        if not fields or fields[0].lower() == "processed" or fields[0].startswith(";"):
            continue
        if len(fields) not in (22, 29):
            raise ValueError("unrecognized water surface row")
        vertices = (len(fields) - 1) // 7
        water_faces[vertices] += 1
        for v in range(vertices):
            extent = max(extent, abs(float(fields[7 * v])), abs(float(fields[7 * v + 1])))
    instances = manifest["instances"]
    scenes = manifest["scenes"]
    # An upper bound for each pool when the original executable classifies placements.
    # Preserve room for the stock gameplay resources retained in the clone.
    size = max(6000, 6000 * math.ceil((2 * extent + 400) / 6000))
    return {
        "IMG LIMITS": {
            "Max number of IMG archives": max(8, 3 + base_archives + len(manifest["archives"]))
        },
        "IPL": {
            "Buildings": max(13000, instances + 128),
            "Dummies": max(2500, instances + 128),
            "Inst entries per file": max(4096, 1 + max(s["instances"] for s in scenes)),
            "Entity index array": max(40, len(scenes) + 8),
        },
        "IDE LIMITS": {
            "IDE Objects Type 1": 14000 + sections["objs"],
            "Timed Objects": 169 + sections["tobj"],
            "Hier Objects": 92 + sections["anim"],
        },
        "DYNAMIC LIMITS": {"ColModels": 10150 + manifest["collisions"]},
        "ID LIMITS": {
            "Apply ID limit patch": 1,
            "FILE_TYPE_DFF": max(20000, highest_model + 1),
            "FILE_TYPE_TXD": 5000 + manifest["textures"],
            "FILE_TYPE_COL": 255 + manifest["effectiveEntries"].get(".col", 0),
            "FILE_TYPE_IPL": 256 + len(scenes),
        },
        "MAP LIMITS": {"World map size": size, "Water map size": size},
        "WATER LIMITS": {
            "Water triangles": max(6, water_faces[3]),
            "Water quads": max(301, water_faces[4]),
            "Water vertices": max(1021, 3 * water_faces[3] + 4 * water_faces[4]),
        },
    }


def merge_limits(original, needed):
    """Retain comments, unrelated preferences and higher limits in an existing installation."""
    result = []
    visited = set()
    sections = {s.casefold(): s for s in needed}
    keys = {s: {k.casefold(): k for k in entries} for s, entries in needed.items()}
    section = None
    seen_sections = set()

    def complete(group):
        if group:
            result.extend(
                f"{k} = {v}" for k, v in needed[group].items() if (group, k) not in visited
            )

    for line in original.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            complete(section)
            section = sections.get(stripped[1 : stripped.index("]")].casefold())
            if section and section in seen_sections:
                raise ValueError(f"duplicate limit section {section}")
            seen_sections.add(section)
        elif section and "=" in line:
            name, _, val = line.partition("=")
            key = keys[section].get(name.strip().casefold())
            if key:
                if (section, key) in visited:
                    raise ValueError(f"duplicate limit {key}")
                visited.add((section, key))
                number = val.partition(";")[0].partition("#")[0].strip()
                if int(number) < needed[section][key]:
                    line = line.replace(
                        "=" + val, "=" + val.replace(number, str(needed[section][key]), 1), 1
                    )
        result.append(line)
    complete(section)
    for group in needed:
        if group not in seen_sections:
            result.append(f"\n[{group}]")
            complete(group)
    return "\n".join(result) + "\n"
