"""The always-arrow worker must have its learned fallback in the image."""
from pathlib import Path
import unittest


class ArrowRuntimePackageTests(unittest.TestCase):
    def test_learned_arrow_asset_is_in_the_docker_runtime(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('!python/arrow_head_v1.json', (root / '.dockerignore').read_text())
        self.assertIn('COPY python/arrow_head_v1.json /app/python/arrow_head_v1.json',
                      (root / 'Dockerfile').read_text())
        self.assertTrue((root / 'python/arrow_head_v1.json').is_file())


if __name__ == '__main__':
    unittest.main()
