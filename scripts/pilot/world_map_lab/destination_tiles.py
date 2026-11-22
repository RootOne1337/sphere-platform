"""Revision-bound overview and native-resolution tiles of the navigation map."""

import hashlib
import json
from io import BytesIO
from urllib.request import urlopen

from PIL import Image


class DestinationTiles:
    tile_size = 512

    def __init__(self, planner, *, terrain_folder=None, map_revision=None, bounds=None):
        self.files = {}
        digest = hashlib.sha256(b"destination-tiles-v1")
        for layer, source in (("terrain", "world"), ("roads", "drive"), ("walk", "walk")):
            if layer == "terrain" and terrain_folder is not None:
                proof = json.loads((terrain_folder / "ariane-world-render.json").read_bytes())
                ordered_bounds = [proof["bounds"][side] for side in ("left", "right", "bottom", "top")]
                raw = (terrain_folder / "ariane-world-top.png").read_bytes()
                if (
                    proof["placementRevision"] != map_revision or ordered_bounds != list(bounds)
                    or hashlib.sha256(raw).hexdigest() != proof["views"]["top"]["sha256"]
                ):
                    raise ValueError("terrain overview is not bound to the planner's world")
            else:
                with urlopen(f"{planner}/{source}.png", timeout=12) as response:
                    raw = response.read()
            digest.update(hashlib.sha256(raw).digest())
            with Image.open(BytesIO(raw)) as image:
                if layer == "terrain":
                    self.size = image.size
                if image.size != self.size:
                    raise ValueError("road overlay and basemap dimensions differ")
                overview = image.copy()
                overview.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                self.encode(f"{layer}/overview", overview)
                for y in range(0, image.height, self.tile_size):
                    for x in range(0, image.width, self.tile_size):
                        box = (
                            x,
                            y,
                            min(x + self.tile_size, image.width),
                            min(y + self.tile_size, image.height),
                        )
                        self.encode(
                            f"{layer}/{x // self.tile_size}-{y // self.tile_size}", image.crop(box)
                        )
        self.revision = digest.hexdigest()

    def encode(self, key, image):
        output = BytesIO()
        image.save(output, format="WEBP", quality=87, method=3)
        self.files[key + ".webp"] = output.getvalue()

    def manifest(self):
        return dict(
            revision=self.revision, width=self.size[0], height=self.size[1], tileSize=self.tile_size
        )
