"""The public checkout must preserve the relative skill/runtime layout."""
from pathlib import Path
import unittest


class DistributionTests(unittest.TestCase):
    def test_public_bundle_contains_linked_runtime_skill_and_examples(self):
        root = Path(__file__).resolve().parents[1]
        required = [
            'README.md', 'LICENSE', '.github/workflows/tests.yml',
            'live-canvas/SKILL.md', 'live-canvas/scripts/live_canvas.py',
            'session-canvas/canvas.py', 'session-canvas/index.html',
            'session-canvas/client_hooks.py', 'session-canvas/install_clients.py',
            'session-canvas/auto_open.py', 'session-canvas/typesafe_presentation.py',
            'session-canvas/codex_startup.py', 'session-canvas/opencode-plugin.mjs',
            'session-canvas/opencode_install.py', 'session-canvas/opencode_bridge.py',
            'session-canvas/library.py',
            'session-canvas/README.md', 'session-canvas/DESIGN.md',
        ]
        for experimental in ("board", "session-canvas/board-assets", "session-canvas/board.py", "session-canvas/collaboration.py"):
            self.assertFalse((root / experimental).exists(), experimental)
        for relative in required:
            with self.subTest(path=relative):
                self.assertTrue((root / relative).is_file())
        self.assertEqual(len(list((root / 'session-canvas/examples').glob('*.json'))), 6)
        self.assertEqual((root / 'live-canvas/scripts/live_canvas.py').resolve().parents[2], root)


if __name__ == '__main__':
    unittest.main()
