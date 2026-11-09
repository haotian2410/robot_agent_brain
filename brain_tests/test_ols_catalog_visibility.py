"""OLS list visibility must not weaken full metadata parity checks."""
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from robot_agent_brain.web.assets import check_ols


class CatalogVisibilityTest(unittest.TestCase):
    def test_hidden_assets_are_not_listed_but_metadata_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, plural in [('model', 'models'), ('robot', 'robots'), ('scene', 'scenes')]:
                base = root / plural
                (base / '1').mkdir(parents=True)
                index = ([{'id': 1, 'name': kind, 'no_display': True}] if kind == 'scene'
                         else {'by_id': {'1': kind}, 'no_display': {'1': True}})
                (base / f'{kind}_index.json').write_text(json.dumps(index), encoding='utf-8')
                (base / '1' / f'{kind}.json').write_text('{"value": 1}', encoding='utf-8')
            calls = []
            corrupt = False

            def handler(request):
                calls.append(request.url.path)
                if request.url.path == '/list':
                    return httpx.Response(200, json={'items': []})
                return httpx.Response(200, json={'value': 2 if corrupt else 1})

            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = check_ols(client, 'http://127.0.0.1:8000', root)
                self.assertTrue(result['matched'])
                self.assertEqual(result['counts'], {'model': 1, 'robot': 1, 'scene': 1})
                self.assertTrue({'/model', '/robot', '/scene'} <= set(calls))
                corrupt = True
                with self.assertRaisesRegex(ValueError, 'ols_metadata_mismatch:model:1'):
                    check_ols(client, 'http://127.0.0.1:8000', root)


if __name__ == '__main__':
    unittest.main()
