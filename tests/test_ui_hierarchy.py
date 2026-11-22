"""A hierarchy used for selecting elements must be complete and bounded."""
import pytest

from backend.services.ui_hierarchy import InvalidUiHierarchy, display_size, parse_hierarchy


def test_rotation_override_and_all_attributes_keep_positional_xpath():
    size = display_size("Physical size: 1080x1920\nOverride size: 540x960\n")
    xml = '<hierarchy rotation="1"><node bounds="[0,0][960,540]" class="root"><node text="Привет &amp; мир" custom="retained" bounds="[10,20][30,40]"/><node bounds="[-5,-4][20,20]"/></node></hierarchy>'
    width, height, rotation, nodes = parse_hierarchy(xml, size)
    assert (width, height, rotation) == (960, 540, 1)
    assert [n.xpath for n in nodes] == ["/hierarchy/node[1]", "/hierarchy/node[1]/node[1]", "/hierarchy/node[1]/node[2]"]
    assert nodes[1].attributes["text"] == "Привет & мир"
    assert nodes[1].attributes["custom"] == "retained"
    assert nodes[1].parent_id == 0 and nodes[1].depth == 1
    assert nodes[2].bounds.left == 0


@pytest.mark.parametrize("xml", [
    '<hierarchy rotation="0"><node/>',
    '<!DOCTYPE hierarchy [<!ENTITY secret SYSTEM "file:///private">]><hierarchy rotation="0"/>',
    '<hierarchy rotation="0">' + '<node>' * 65 + '</node>' * 65 + '</hierarchy>',
    '<hierarchy rotation="0">' + '<node/>' * 4097 + '</hierarchy>',
    '<hierarchy rotation="0"><node text="' + 'x' * 4097 + '"/></hierarchy>',
    '<hierarchy rotation="0"><node text="' + '界' * 65000 + '"/></hierarchy>',
    '<other rotation="0"/>', '<hierarchy rotation="4"/>', '<hierarchy/>',
    '<hierarchy rotation="0"><other/></hierarchy>',
], ids=["partial", "entity", "depth", "nodes", "attribute", "utf8-bytes", "root", "rotation", "missing-rotation", "unknown-tag"])
def test_rejects_partial_entities_deep_wide_or_malformed_tree(xml):
    with pytest.raises(InvalidUiHierarchy):
        parse_hierarchy(xml, (540, 960))


@pytest.mark.parametrize("output", ["", "Physical size: 0x10", "Override size: 20000x100", "wm: permission denied"])
def test_requires_known_display_geometry(output):
    with pytest.raises(InvalidUiHierarchy):
        display_size(output)


def test_empty_tree_and_offscreen_nodes_are_truthful_not_invented_elements():
    assert parse_hierarchy('<hierarchy rotation="0"/>', (100, 200))[3] == []
    nodes = parse_hierarchy('<hierarchy rotation="0"><node bounds="[100,100][120,120]"/></hierarchy>', (100, 200))[3]
    assert nodes[0].bounds is None
    assert nodes[0].attributes["bounds"] == "[100,100][120,120]"
