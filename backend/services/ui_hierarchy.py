"""Parse a complete bounded dump; no arbitrary XPath or XML entity evaluation."""

import re
from xml.etree import ElementTree as ET

from backend.schemas.ui_hierarchy import UiBounds, UiHierarchyNode

MAX_XML_BYTES = 128 * 1024
MAX_NODES = 4096
MAX_DEPTH = 64


class InvalidUiHierarchy(ValueError):
    pass


def display_size(output: str) -> tuple[int, int]:
    sizes = re.findall(r"(?:Physical|Override) size: (\d+)x(\d+)", output)
    if not sizes:
        raise InvalidUiHierarchy("display_geometry_unavailable")
    if any(len(part) > 5 for part in sizes[-1]):
        raise InvalidUiHierarchy("display_geometry_invalid")
    width, height = map(int, sizes[-1])
    if not (0 < width <= 16384 and 0 < height <= 16384):
        raise InvalidUiHierarchy("display_geometry_invalid")
    return width, height


def parse_hierarchy(xml: str, size: tuple[int, int]) -> tuple[int, int, int, list[UiHierarchyNode]]:
    if not isinstance(xml, str):
        raise InvalidUiHierarchy("ui_dump_invalid_text")
    try:
        byte_count = len(xml.encode("utf-8"))
    except UnicodeError as exc:
        raise InvalidUiHierarchy("ui_dump_invalid_text") from exc
    if byte_count > MAX_XML_BYTES:
        raise InvalidUiHierarchy("ui_dump_byte_budget_exceeded")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.IGNORECASE):
        raise InvalidUiHierarchy("ui_dump_entities_forbidden")
    parser = ET.XMLPullParser(events=("start", "end"))
    stack: list[tuple[int | None, str, int]] = []
    nodes: list[UiHierarchyNode] = []
    rotation = None
    width, height = size
    try:
        # Consume events as input arrives, enforcing depth before constructing
        # an arbitrarily nested tree. The byte ceiling applies before parsing.
        for offset in range(0, len(xml), 2048):
            parser.feed(xml[offset:offset + 2048])
            for event, node in parser.read_events():
                # ElementTree's event type also permits namespace payloads.
                # This parser requests only element events; reject any other
                # payload before accessing the node or accepting a snapshot.
                if not isinstance(node, ET.Element):
                    raise InvalidUiHierarchy("ui_dump_structure_invalid")
                if event == "end":
                    stack.pop()
                    node.clear()
                    continue
                if not stack:
                    if rotation is not None or node.tag != "hierarchy":
                        raise InvalidUiHierarchy("ui_dump_root_invalid")
                    if node.attrib.get("rotation") not in {"0", "1", "2", "3"}:
                        raise InvalidUiHierarchy("ui_dump_rotation_invalid")
                    rotation = int(node.attrib["rotation"])
                    if rotation in (1, 3):
                        width, height = height, width
                    stack.append((None, "/hierarchy", 0))
                    continue
                if node.tag != "node" or len(stack) > MAX_DEPTH or len(nodes) >= MAX_NODES:
                    raise InvalidUiHierarchy("ui_dump_structure_budget_exceeded")
                if len(node.attrib) > 64 or any(len(k) > 128 or len(v) > 4096 for k, v in node.attrib.items()):
                    raise InvalidUiHierarchy("ui_dump_attribute_budget_exceeded")
                parent_id, parent_xpath, sibling_count = stack[-1]
                stack[-1] = (parent_id, parent_xpath, sibling_count + 1)
                xpath = f"{parent_xpath}/node[{sibling_count + 1}]"
                bounds = None
                match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.attrib.get("bounds", ""))
                if match:
                    left, top, right, bottom = map(int, match.groups())
                    # Preserve raw bounds in attributes; hit testing uses only
                    # the non-empty intersection with the reported display.
                    left, top = max(0, left), max(0, top)
                    right, bottom = min(width, right), min(height, bottom)
                    if left < right and top < bottom:
                        bounds = UiBounds(left=left, top=top, right=right, bottom=bottom)
                item = UiHierarchyNode(id=len(nodes), parent_id=parent_id, depth=len(stack) - 1,
                                       xpath=xpath, attributes=dict(node.attrib), bounds=bounds)
                nodes.append(item)
                stack.append((item.id, xpath, 0))
        parser.close()
    except (ET.ParseError, IndexError) as exc:
        raise InvalidUiHierarchy("ui_dump_incomplete_or_invalid") from exc
    if stack or rotation is None:
        raise InvalidUiHierarchy("ui_dump_incomplete_or_invalid")
    return width, height, rotation, nodes
