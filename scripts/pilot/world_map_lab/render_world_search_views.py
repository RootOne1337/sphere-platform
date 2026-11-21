"""Build a resumable visual search gallery from the road mesh across the entire world."""

import argparse
import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.live_destination import RoadMap


def select_sites(faces, spacing):
    counts = faces["vertices"]
    xyz = faces["xyz"]
    if not np.all((counts >= 3) & (counts <= xyz.shape[1])):
        raise ValueError("invalid road polygon")
    mask = np.arange(xyz.shape[1])[None, :] < counts[:, None]
    centers = np.where(mask[:, :, None], xyz, 0.0).sum(axis=1) / counts[:, None]
    cells = np.floor(centers[:, :2] / spacing).astype(int)
    # Keep a real polygon center on each elevation instead of averaging stacked roads.
    groups = defaultdict(list)
    for i, cell in enumerate(cells):
        groups[tuple(cell)].append(i)
    result = []
    for col, row in sorted(groups, key=lambda ij: (ij[0], ij[1] if ij[0] % 2 else -ij[1])):
        pts = centers[groups[col, row]]
        xy = np.array([col + 0.5, row + 0.5]) * spacing
        ordered = np.argsort(np.linalg.norm(pts[:, :2] - xy, axis=1), kind="stable")
        levels = []
        for i in ordered:
            x, y, z = pts[i]
            if all(abs(z - other) > 6 for other in levels):
                result.append([round(x, 3), round(y, 3), round(z + 1.45, 3)])
                levels.append(z)
    return result


CAPTURE = """async ({width,height})=>{
const {createWorld}=await import('/journey/scene.mjs');
const config=await (await fetch('/journey/route.json')).json();
const canvas=document.querySelector('canvas');
const world=await createWorld(canvas,config);
world.size(width,height);world.vehicle(null,0,false);
const strip=document.createElement('canvas');strip.width=4*width;strip.height=2*height;
const c=strip.getContext('2d');window.searchViews=async eye=>{
 await world.ensure(...eye);
 for(let i=0;i<8;i++){
  world.pose([...eye,i*Math.PI/4,-.015]);
  world.renderer.render(world.scene,world.camera);
  c.drawImage(canvas,i%4*width,Math.floor(i/4)*height,width,height);
 }
 return strip.toDataURL('image/jpeg',.9).split(',')[1]
};
return {vfov:world.camera.fov,aspect:world.camera.aspect};
}"""


def candidate_regions(search, limit):
    """Share a bounded rendering budget between independently rotated query groups."""
    groups = sorted(
        search["results"], key=lambda g: (g["distinctDirections"], len(g["frames"])), reverse=True
    )
    if not groups:
        return []
    if groups[0]["distinctDirections"] >= 3:
        groups = [group for group in groups if group["distinctDirections"] >= 2]
    seeds = []
    for rank in range(max((len(g["candidates"]) for g in groups), default=0)):
        for group in groups:
            if rank >= len(group["candidates"]):
                continue
            eye = group["candidates"][rank]["eye"]
            if any(
                np.linalg.norm(np.subtract(eye[:2], old[:2])) < 45 and abs(eye[2] - old[2]) < 5
                for old in seeds
            ):
                continue
            seeds.append(eye)
            if len(seeds) == limit:
                return seeds
    return seeds


def build(args):
    if not 4 <= args.spacing <= 512:
        raise ValueError("invalid survey spacing")
    road = RoadMap(args.planner)
    with np.load(args.folder / "drive-faces.npz", allow_pickle=False) as archive:
        if str(archive["geometry"]) != road.meta["geometrySha256"]:
            raise ValueError("road source mismatch")
        faces = archive["faces"]
        seeds = []
        if args.candidates:
            search = json.loads(args.candidates.read_bytes())
            if search["revision"] != road.meta["placementRevision"]:
                raise ValueError("search candidates belong to a different map")
            if not (1 <= args.regions <= 12 and 8 <= args.radius <= 256):
                raise ValueError("invalid candidate search area")
            seeds = candidate_regions(search, args.regions)
            if not seeds:
                raise ValueError("no world search candidates")
            counts = faces["vertices"]
            mask = np.arange(faces["xyz"].shape[1])[None, :] < counts[:, None]
            center = np.where(mask[:, :, None], faces["xyz"], 0).sum(1) / counts[:, None]
            eligible = np.zeros(len(faces), dtype=bool)
            for eye in seeds:
                eligible |= np.linalg.norm(center[:, :2] - eye[:2], axis=1) <= args.radius
            faces = faces[eligible]
        sites = select_sites(faces, args.spacing)
        if not sites:
            raise ValueError("no road surfaces in the search area")
    cfg = (args.folder / "journey/route.json").read_bytes()
    if json.loads(cfg)["revision"] != road.meta["placementRevision"]:
        raise ValueError("scene revision mismatch")
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    manifest = dict(
        revision=road.meta["placementRevision"],
        geometry=road.meta["geometrySha256"],
        spacing=args.spacing,
        directions=8,
        width=256,
        height=144,
        eyes=sites,
        renderer=hashlib.sha256(CAPTURE.encode()).hexdigest(),
    )
    if args.candidates:
        manifest["parentSearch"] = hashlib.sha256(args.candidates.read_bytes()).hexdigest()
        manifest["candidateRadius"] = args.radius
        manifest["regionBudget"] = args.regions
    metadata = output / "survey.json"
    if metadata.exists() and json.loads(metadata.read_bytes()) != manifest:
        raise ValueError("output already contains a different survey")
    metadata.write_text(json.dumps(manifest), encoding="utf8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--enable-gpu", "--use-angle=d3d11"])
        page = browser.new_page()
        page.route(
            "**/world-search-gallery",
            lambda route: route.fulfill(
                content_type="text/html",
                body='<canvas></canvas><script type="importmap">{"imports":{"three":"/detail/js/three.module.js"}}</script>',
            ),
        )
        page.route(
            "**/journey/route.json",
            lambda route: route.fulfill(content_type="application/json", body=cfg),
        )
        page.goto(road.base + "/world-search-gallery")
        lens = page.evaluate(CAPTURE, dict(width=manifest["width"], height=manifest["height"]))
        print("Sites", len(sites), "lens", lens, flush=True)
        for i, eye in enumerate(sites):
            dst = output / f"{i:05}.jpg"
            if dst.is_file():
                existing = cv2.imread(str(dst), cv2.IMREAD_REDUCED_GRAYSCALE_4)
                if existing is not None and existing.shape == (72, 256):
                    continue
            data = base64.b64decode(page.evaluate("eye=>searchViews(eye)", eye), validate=True)
            im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if im is None or im.shape != (288, 1024):
                raise ValueError("incomplete panorama")
            tmp = dst.with_suffix(".partial")
            tmp.write_bytes(data)
            tmp.replace(dst)
            if (i + 1) % 100 == 0:
                print(i + 1, "/", len(sites), flush=True)
        browser.close()
    print("Complete", len(sites) * 8, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spacing", type=int, default=128)
    parser.add_argument("--planner", default="http://127.0.0.1:8817")
    parser.add_argument(
        "--candidates", type=Path, help="refine automatically retrieved world areas"
    )
    parser.add_argument("--regions", type=int, default=3)
    parser.add_argument("--radius", type=float, default=105)
    build(parser.parse_args())
