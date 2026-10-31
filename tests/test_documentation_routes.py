"""Keep the documented Web route inventory aligned with App Router page files.

This checks names only, not page behaviour, permissions, deployments or runtime.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebRouteInventoryTests(unittest.TestCase):
    def test_documented_page_routes_match_source_tree(self):
        app = ROOT / 'frontend' / 'app'
        source = set()
        for page in app.rglob('page.tsx'):
            parts = page.relative_to(app).parts[:-1]
            route = '/' + '/'.join(part for part in parts if not (part.startswith('(') and part.endswith(')')))
            source.add(route)
        guide = (ROOT / 'docs' / 'web-ui-guide.md').read_text(encoding='utf-8')
        table = guide.split('## Карта маршрутов', 1)[1].split('## ', 1)[0]
        documented = re.findall(r'^\| `(/[^`]*)` \|', table, flags=re.MULTILINE)
        self.assertEqual(len(documented), len(set(documented)), 'Duplicate route in guide')
        self.assertSetEqual(set(documented), source, 'Route inventory differs from frontend/app')


if __name__ == '__main__':
    unittest.main()
