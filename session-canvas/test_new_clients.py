import json
import tempfile
from pathlib import Path
from unittest import TestCase,mock
import codex_startup
import opencode_install
import opencode_bridge
import install_clients
import canvas

class StartupTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)
    def test_codex_setup_preserves_existing_instructions_and_is_idempotent(self):
        path=self.home/'.codex/AGENTS.md';path.parent.mkdir();path.write_text('Keep these project conventions.\n')
        codex_startup.apply(codex_startup.plan(self.home));one=path.read_text()
        self.assertTrue(one.startswith('Keep these project conventions.'));self.assertEqual(one.count(codex_startup.BEGIN),1)
        codex_startup.apply(codex_startup.plan(self.home));self.assertEqual(path.read_text(),one)
        self.assertFalse((self.home/'.codex/hooks.json').exists())
    def test_codex_malformed_marker_is_preserved(self):
        path=self.home/'.codex/AGENTS.md';path.parent.mkdir();path.write_text(codex_startup.BEGIN)
        with self.assertRaises(ValueError):codex_startup.plan(self.home)
        self.assertEqual(path.read_text(),codex_startup.BEGIN)
    def test_opencode_install_and_uninstall_preserves_other_plugins(self):
        other=self.home/'.config/opencode/plugins/other.js';other.parent.mkdir(parents=True);other.write_text('export default {};')
        opencode_install.apply(opencode_install.plan(self.home));self.assertTrue(opencode_install.plan(self.home)['installed'])
        opencode_install.apply(opencode_install.plan(self.home,True));self.assertEqual(other.read_text(),'export default {};')
    def test_opencode_modified_plugin_is_never_overwritten(self):
        opencode_install.apply(opencode_install.plan(self.home));path=self.home/'.config/opencode/plugins/live-canvas.js';path.write_text('User edit')
        with self.assertRaises(ValueError):opencode_install.plan(self.home)
        self.assertEqual(path.read_text(),'User edit')
    def legacy_install(self):
        opencode_install.apply(opencode_install.plan(self.home))
        base=self.home/'.config/opencode'
        (base/'plugins/live-canvas.js').rename(base/'plugins/live-canvas.mjs')
        manifest=base/'.live-canvas-install.json';data=json.loads(manifest.read_text());data.pop('filename');manifest.write_text(json.dumps(data))
        return base
    def test_opencode_migrates_owned_legacy_plugin_to_discoverable_extension(self):
        base=self.legacy_install()
        self.assertFalse(opencode_install.plan(self.home)['installed'])
        self.assertTrue(opencode_install.apply(opencode_install.plan(self.home))['changed'])
        self.assertFalse((base/'plugins/live-canvas.mjs').exists())
        self.assertTrue((base/'plugins/live-canvas.js').exists())
        self.assertTrue(opencode_install.plan(self.home)['installed'])
    def test_opencode_legacy_upgrade_preserves_collision(self):
        base=self.legacy_install();path=base/'plugins/live-canvas.js';path.write_text('Other plugin')
        with self.assertRaises(ValueError):opencode_install.plan(self.home)
        self.assertEqual(path.read_text(),'Other plugin')
        self.assertTrue((base/'plugins/live-canvas.mjs').exists())
    def test_opencode_legacy_edit_is_preserved(self):
        base=self.legacy_install();path=base/'plugins/live-canvas.mjs';path.write_text('User edit')
        with self.assertRaises(ValueError):opencode_install.plan(self.home)
        self.assertEqual(path.read_text(),'User edit')
    def test_opencode_legacy_uninstall_removes_only_owned_plugin(self):
        base=self.legacy_install()
        opencode_install.apply(opencode_install.plan(self.home,True))
        self.assertFalse((base/'plugins/live-canvas.mjs').exists())
    def test_opencode_skips_subagents_and_preserves_session_identity(self):
        with mock.patch('auto_open.prepare') as prepare:
            opencode_bridge.handle({'event':'start','session_id':'session-a','parent_id':'parent'},self.home);prepare.assert_not_called()
        canvas.mutate(self.home,'opencode:session-a',lambda s:s.update(enabled=True))
        opencode_bridge.handle({'event':'message','session_id':'session-a','role':'user','text':'My instruction','message_id':'msg-a'},self.home)
        state=canvas.read_json(canvas.task_dir(self.home,'opencode:session-a')/'state.json');self.assertEqual(state['automatic']['latest_user']['text'],'My instruction')
