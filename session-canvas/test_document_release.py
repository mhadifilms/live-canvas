"""Document release must remain independent of the experimental renderer."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase
import canvas
import library
import typesafe_presentation as presentation

class DocumentReleaseTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_snapshot_uses_document_widgets_and_safe_embedded_state(self):
        state = canvas.initial('opencode:example')
        state['content']['title'] = '</script><script>alert(1)</script>'
        state['content']['sections'] = [{'id':'review','title':'Review','blocks':[{'id':'c','type':'checklist','items':[{'text':'Read this','checked':False}]}]}]
        state['transcript'] = {'path':'/private/transcript'}
        state['board'] = {'elements':[{'text':'experimental legacy content'}]}
        library.snapshot(self.root, state)
        folder = canvas.task_dir(self.root, state['thread'])
        html = (folder/'canvas.html').read_text()
        self.assertIn('renderChecklist', html)
        self.assertIn('Read this', html)
        self.assertNotIn('</script><script>alert', html)
        self.assertNotIn('/private/transcript', html)
        self.assertNotIn('experimental legacy content', html)
        self.assertNotIn('async function poll', html)
        self.assertFalse((folder/'board.excalidraw').exists())
        self.assertEqual(json.loads((folder/'chat.json').read_text())['session_id'], 'example')
        self.assertEqual((folder/'canvas.html').stat().st_mode & 0o777, 0o600)

    def test_updates_keep_legacy_data_but_render_only_document_content(self):
        canvas.mutate(self.root, 't', lambda state: state.update(enabled=True, board={'human_revision':4}))
        state = canvas.update_content(self.root, 't', {'title':'Document'})
        self.assertEqual(state['board']['human_revision'], 4)
        self.assertIn('Document', (canvas.task_dir(self.root, 't')/'canvas.html').read_text())
        canvas.ingest(self.root,'t',{'kind':'user','text':'Visible instruction'})
        self.assertIn('Visible instruction',(canvas.task_dir(self.root,'t')/'conversation.jsonl').read_text())

    def test_rich_context_requires_opt_in_and_ignores_tools(self):
        state = canvas.initial('t')
        state['content']['sections'] = [{'id':str(i),'title':'Section','blocks':[]} for i in range(2)]
        before = presentation.source_hash(state)
        rich_before = presentation.source_hash(state, True)
        state['feed'] = [{'kind':'user','text':'Visible question'}, {'kind':'activity','text':'Private tool output'}]
        self.assertEqual(before, presentation.source_hash(state))
        self.assertNotEqual(rich_before, presentation.source_hash(state, True))
        plain, _ = presentation.build_request(state)
        rich, _ = presentation.build_request(state, True)
        self.assertNotIn(b'Visible question', plain)
        self.assertIn(b'Visible question', rich)
        self.assertNotIn(b'Private tool output', rich)
        self.assertLessEqual(len(rich), presentation.MAX_INPUT_BYTES)
