"""Keep near collision-bearing placements in the stock engine's collidable building class."""

from scripts.pilot.world_map_lab.native_collisions import COL


def collision_names(data):
    offset = 0
    names = set()
    while data[offset : offset + 4] in (b"COLL", b"COL2", b"COL3"):
        _, size, name, _ = COL.unpack_from(data, offset)
        end = offset + size + 8
        if size < 24 or end > len(data):
            raise ValueError("invalid collision record")
        names.add(name.partition(b"\0")[0].decode("ascii").lower())
        offset = end
    if not names or any(data[offset:]):
        raise ValueError("unexpected collision archive")
    return names


def near_model_distances(ide, scenes, colliders):
    near, far = set(), set()
    for scene in scenes:
        instances = []
        section = None
        for raw in scene.splitlines():
            row = raw.partition("#")[0].strip().lower()
            if not row:
                continue
            if section is None:
                section = row
            elif row == "end":
                section = None
            elif section == "inst":
                fields = row.split(",")
                instances.append((fields[1].strip(), int(fields[-1])))
        parents = {idx for _, idx in instances if idx >= 0}
        if parents and max(parents) >= len(instances):
            raise ValueError("out-of-range placement parent")
        for i, (model, _) in enumerate(instances):
            (far if i in parents else near).add(model)
    eligible = (near - far) & colliders
    changed = {}
    section = None
    out = []
    for raw in ide.splitlines():
        line = raw.partition("#")[0].strip().lower()
        if line and section is None:
            section = line
        elif line == "end":
            section = None
        elif line and section in ("objs", "tobj", "anim"):
            values = raw.split(",")
            model = values[1].strip().lower()
            index = 4 if section == "anim" else 3
            if model in eligible and float(values[index]) > 150.0:
                # LinkLods calls SetupBigBuilding above scaled distance 300, which clears
                # bUsesCollision. Leave up to 2x headroom and preserve all far models.
                changed[model] = float(values[index])
                values[index] = " 150"
                raw = ",".join(values)
        out.append(raw)
    return "\n".join(out) + "\n", dict(changed=changed, mixedRoles=sorted(near & far & colliders))
