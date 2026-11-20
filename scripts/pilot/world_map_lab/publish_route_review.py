"""Bind per-site visual and physical evidence to the exact routes before and after rebaking."""

import argparse
import json
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.world_navmesh import Network, checksum


def read(folder, name):
    return json.loads((folder / name).read_bytes())


def point_on(nav, point):
    x, y, z = map(float, point)
    h = nav.levels(x, y)
    return [x, y, min(h, key=lambda a: abs(a - z))] if h else [x, y, z]


def result(nav, a, b):
    r = nav.route(a, b)
    return {"status": r["status"], "length": round(r["length"], 1), "path": r["path"]}


def publish(base, new):
    review = read(new, "clearance.json")
    old = read(base, "fixed-pair-recheck.json")
    now = read(new, "fixed-pair-recheck.json")
    alt = read(new, "alternate-crossings.json")
    bench = read(new, "route-benchmark.json")
    scene = read(new, "detail-scene.json")
    sites = []
    failures = []
    summary = {}
    with ExitStack() as stack:
        for mode in ("drive", "walk"):
            before = stack.enter_context(Network(base, mode, adapter=new / "ariane-nav.dll"))
            after = stack.enter_context(Network(new, mode))
            if review["components"][mode]["meshSha256"] != checksum(
                base / f"{mode}.nav.zip"
            ) or bench[mode]["mesh"] != checksum(new / f"{mode}.nav.zip"):
                raise ValueError("inspection or benchmark does not match published routes")
            if scene["revision"] != after.meta["placementRevision"]:
                raise ValueError("scene revision mismatch")
            pairs = now[mode]["pairs"]
            prior = old[mode]["pairs"]
            if len(pairs) != len(prior) or any(
                a[k] != b[k] for a, b in zip(prior, pairs, strict=True) for k in ("start", "end")
            ):
                raise ValueError("coordinates changed")
            summary[mode] = {
                "before": sum(x["after"] == "complete" for x in prior),
                "after": sum(x["after"] == "complete" for x in pairs),
                "total": len(pairs),
                "lost": sum(
                    a["after"] == "complete" and b["after"] != "complete"
                    for a, b in zip(prior, pairs, strict=True)
                ),
                "manifest": after.meta,
                "timing": bench[mode]["timing"],
                "lengthRatioMax": bench[mode]["lengthRatioMax"],
            }
            with np.load(base / f"{mode}-faces.npz", allow_pickle=False) as z:
                faces = z["faces"]
            centers = faces["xyz"].sum(axis=1) / faces["vertices"][:, None]
            trees = {}
            for g in {s["group"] for s in review["sites"] if s["mode"] == mode} | {
                review["components"][mode]["main"]
            }:
                cc = centers[faces["group"] == g]
                trees[g] = (cc, cKDTree(cc))

            def anchor(p, g):
                cc, tree = trees[g]
                _, ii = tree.query(p, k=min(50, len(cc)))
                for i in np.atleast_1d(ii):
                    candidate = point_on(before, cc[i])
                    if before.component(candidate) == g:
                        return candidate
                raise ValueError("no interior anchor")

            bridges = {}
            for s in review["sites"]:
                if s["mode"] != mode:
                    continue
                a = anchor(s["a"], s["group"])
                b = anchor(s["b"], review["components"][mode]["main"])
                p0 = result(before, a, b)
                p1 = result(after, a, b)
                if p0["status"] == "complete":
                    raise ValueError("component anchors already connected on baseline")
                rays = [review["rays"][j] for j in s["samples"]]
                mats = list(dict.fromkeys(h["surfaces"][0][1] for h in rays if h["surfaces"]))
                hits = s["bodyIntersections"]
                maxdz = max(
                    abs(s["a"][2] - s["b"][2]),
                    max(
                        (
                            abs(p["referenceZ"] - p["floor"])
                            for p in s["profile"]
                            if p["floor"] is not None
                        ),
                        default=0,
                    ),
                )
                delta = np.linalg.norm(np.subtract(a, b))
                routed = p1["status"] == "complete"
                if hits:
                    reason = f"Прямой коридор пересекает коллизию. Пересечений граней {hits}."
                    category = "barrier"
                elif abs(s["a"][2] - s["b"][2]) > 3:
                    reason = (
                        f"Концы на разных высотах. Перепад {abs(s['a'][2] - s['b'][2]):.1f} ед."
                    )
                    category = "level"
                elif routed and p1["length"] < max(8, 1.6 * delta) and maxdz < 0.65:
                    reason = "Между внутренними точками прежних раздельных участков появился короткий путь по подтверждённой поверхности."
                    category = "joined"
                elif (
                    any(
                        p["road"] is None or abs(p["road"] - p["referenceZ"]) > 0.65
                        for p in s["profile"]
                    )
                    and mode == "drive"
                ):
                    reason = "На прямой прерывается подтверждённое дорожное покрытие."
                    category = "material"
                elif routed:
                    reason = "Связь между участками подтверждена через другой проход."
                    category = "detour"
                else:
                    reason = "На исследованном участке непрерывный коридор требуемой ширины ещё не подтверждён."
                    category = "open"
                entry = {
                    "id": s["id"],
                    "mode": mode,
                    "position": ((np.asarray(s["a"]) + s["b"]) * 0.5).tolist(),
                    "edge": [s["a"], s["b"]],
                    "anchors": [a, b],
                    "before": p0,
                    "after": p1,
                    "reason": reason,
                    "category": category,
                    "materials": mats,
                    "hits": hits,
                    "samples": rays,
                    "profile": s["profile"],
                    "intersections": s["firstIntersections"],
                }
                if s["id"].startswith("G"):
                    sites.append(entry)
                else:
                    bridges[s["group"]] = entry
            for r in review["failures"]:
                if r["mode"] != mode:
                    continue
                i = int(r["id"][1:]) - 1
                changed = pairs[i]["after"] == "complete"
                g = next(g for g in r["groups"] if g != review["components"][mode]["main"])
                site = bridges[g]
                other = next((x for x in alt if x["mode"] == mode and i + 1 in x["pairs"]), None)
                count = len(other["sites"]) if other else 0
                reason = site["reason"]
                if changed:
                    reason = (
                        "На прежних координатах подтверждён сквозной путь. Более мелкие ячейки выделили проход между пешеходными участками."
                        if mode == "walk"
                        else "На прежних координатах подтверждён сквозной путь через дорожную сеть после исправления проверки габаритов и покрытий."
                    )
                elif other:
                    cand = other["sites"]
                    if not cand:
                        reason = f"Ближайшие вершины основной сети в {other['nearest']:.1f} ед. На прямой проверены материалы и коллизии. Подтверждённого соединения с основной сетью пока нет."
                    elif all(x["body"] for x in cand):
                        reason = f"В каждом из {count} проверенных прямых коридоров корпус пересекает коллизию. Ближайшая пара краёв в {other['nearest']:.2f} ед."
                    elif all(x["dz"] > 1 for x in cand):
                        reason = f"У {count} проверенных переходов высота опоры расходится с прямой между уровнями. Старт и цель относятся к разным физическим поверхностям."
                failures.append(
                    {
                        **r,
                        "status": "complete" if changed else pairs[i]["after"],
                        "length": pairs[i]["length"],
                        "reason": reason,
                        "site": site,
                        "rays": [review["rays"][j] for j in r["samples"]],
                        "alternatives": other,
                    }
                )
    from scripts.pilot.world_map_lab.world_trip import TripPlanner

    support = read(new, "route-support.json")
    with Network(new, "drive") as drive, Network(new, "walk") as walk:
        trip = TripPlanner({"drive": drive, "walk": walk}, new)
        for r in failures:
            if r["status"] == "complete":
                route = (drive if r["mode"] == "drive" else walk).route(*r["points"])
                r["lines"] = [{"mode": r["mode"], "path": route["path"]}]
                continue
            result_mixed = trip.route(*r["points"])
            r["lines"] = result_mixed["legs"]
            r["mixed"] = {
                "modes": [leg["mode"] for leg in result_mixed["legs"]],
                "length": result_mixed["length"],
            }
        for mode in ("drive", "walk"):
            if support[mode]["mesh"] != checksum(new / f"{mode}.nav.zip"):
                raise ValueError("stale height checks")
    output = {
        "support": support,
        "summary": summary,
        "sites": sites,
        "failures": failures,
        "scene": scene,
        "bounds": after.meta["bounds"],
    }
    if (new / "api-benchmark.json").is_file():
        api = read(new, "api-benchmark.json")
        if any(api["meshes"][m] != support[m]["mesh"] for m in ("walk", "drive")):
            raise ValueError("stale HTTP benchmark")
        output["httpTiming"] = api["workers"]
    (new / "review.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    html = Path(__file__).with_name("world_review.html").read_text(encoding="utf-8")
    script = Path(__file__).with_name("world_review.js").read_text(encoding="utf-8")
    embedded = json.dumps(output, ensure_ascii=False).replace("<", chr(92) + "u" + "003c")
    html = html.replace("__REVIEW_DATA__", embedded).replace("__REVIEW_JS__", script)
    (new / "navigation-report.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--base", type=Path, required=True)
    a.add_argument("--new", type=Path, required=True)
    q = a.parse_args()
    publish(q.base, q.new)
