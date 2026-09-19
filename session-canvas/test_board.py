import copy
import json
from pathlib import Path
import tempfile
import unittest

import board
import canvas
import collaboration
import typesafe_presentation as jev

class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.thread='shared-board-test'
        self.state=canvas.mutate(self.root,self.thread,lambda s:s.update(enabled=True))
    def current(self):return canvas.read_json(canvas.task_dir(self.root,self.thread)/'state.json')
    def element(self,id='human-note'):return board.text_element(id,'A human note',40,50)
    def save(self,e,bases=None):return board.update(self.root,self.thread,{'elements':[e],'base_versions':bases or {},'files':{}})['board']
    def content(self,text='Agent content'):
        return canvas.update_content(self.root,self.thread,{'sections':[{'id':'work','title':'Working together','blocks':[{'id':'body','type':'text','text':text}]}]})
    def test_concurrent_distinct_objects_merge(self):
        self.save(self.element('a'));self.save(self.element('b'))
        self.assertEqual({e['id'] for e in self.current()['board']['elements']},{'a','b'})
    def test_same_object_conflict_does_not_lose_work(self):
        e=self.element();first=self.save(e);changed={**e,'text':'First writer'};self.save(changed,first['versions'])
        with self.assertRaises(board.Conflict):self.save({**e,'text':'Stale writer'},first['versions'])
        self.assertEqual(self.current()['board']['elements'][0]['text'],'First writer')
    def test_human_edits_survive_agent_projection_and_jev(self):
        s=self.content();scene=s['board'];e=copy.deepcopy(scene['elements'][1]);e.update(text='Human correction',x=900)
        self.save(e,scene['versions']);s=self.content('Revised agent response');protected=next(x for x in s['board']['elements'] if x['id']==e['id'])
        board.apply_presentation(s,{'status':'focused','focus_id':'work','style':{'layout':'focus','emphasis':'blue'}})
        self.assertEqual(protected['text'],'Human correction');self.assertEqual(protected['x'],900)
    def test_editor_bookkeeping_does_not_claim_generated_objects(self):
        s=self.content();e=copy.deepcopy(s['board']['elements'][0]);e.update(version=100,index='a2',seed=2,updated=32)
        self.save(e,s['board']['versions']);self.assertFalse(self.current()['board']['elements'][0]['customData'].get('humanTouched'))
    def test_deleted_human_object_stays_deleted_after_content_change(self):
        s=self.content();e={**s['board']['elements'][0],'isDeleted':True};self.save(e,s['board']['versions']);s=self.content('Updated')
        self.assertTrue(next(x for x in s['board']['elements'] if x['id']==e['id'])['isDeleted'])
    def test_human_undo_is_versioned(self):
        e=self.element();first=self.save(e);second=self.save({**e,'isDeleted':True},first['versions']);self.save(e,second['versions'])
        self.assertFalse(self.current()['board']['elements'][0]['isDeleted'])
    def test_hostile_archive_text_escaped(self):
        e=self.element();e['text']='</text><script>alert(1)</script>';self.save(e)
        saved=(canvas.task_dir(self.root,self.thread)/'canvas.html').read_text()
        self.assertNotIn('<script>',saved);self.assertIn('&lt;script&gt;',saved)
        self.assertTrue((canvas.task_dir(self.root,self.thread)/'board.excalidraw').exists())
    def test_rejects_invalid_geometry_and_links(self):
        for patch in [{'x':float('nan')},{'points':[['0"/>',2]]},{'link':'javascript:alert(1)'},{'customData':[]},{'strokeColor':'url(https://example.org)'}]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):self.save({**self.element(),**patch})
    def test_missing_geometry_cannot_persist_a_broken_scene(self):
        e=self.element();del e['x']
        with self.assertRaises(ValueError):self.save(e)
        self.assertEqual(self.current()['board']['elements'],[])

    def test_human_revision_changes_jev_hash_but_layout_does_not(self):
        s=self.content();before=jev.source_hash(s);board.apply_presentation(s,{'status':'focused','style':{'layout':'focus','emphasis':'blue'}})
        self.assertEqual(before,jev.source_hash(s));self.save(self.element());self.assertNotEqual(before,jev.source_hash(self.current()))
    def test_jev_off_preserves_manual_layout(self):
        s=self.content();collaboration.submit(self.root,self.thread,{'kind':'preference','id':'off','text':'adaptive:off'});s=self.current();before=copy.deepcopy(s['board'])
        board.apply_presentation(s,{'status':'focused','style':{'layout':'focus'}});self.assertEqual(before,s['board'])
    def test_enhanced_context_is_opt_in_and_bounded(self):
        self.content();e=self.element();e['text']='Private board note';self.save(e);s=self.current()
        basic,_=jev.build_request(s,{'rich_context':False});rich,_=jev.build_request(s,{'rich_context':True})
        self.assertNotIn(b'Private board note',basic);self.assertIn(b'Private board note',rich);self.assertLessEqual(len(rich),jev.MAX_INPUT_BYTES)
    def test_presence_does_not_trigger_inference(self):
        s=self.content();before=jev.source_hash(s);revision=s['revision']
        collaboration.submit(self.root,self.thread,{'kind':'presence','id':'test-window'})
        self.assertEqual(before,jev.source_hash(self.current()));self.assertEqual(revision,self.current()['revision'])

class BoardHTTPTests(unittest.TestCase):
    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.thread='http-board'
        canvas.mutate(self.root,self.thread,lambda s:s.update(enabled=True))
        self.route=canvas.task_route(self.root,canvas.key(self.thread));self.server=ThreadingHTTPServer(('127.0.0.1',0),canvas.make_handler(self.root,'test-secret','test-instance'))
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.worker.join();self.tmp.cleanup()
    def request(self,path,body=None,authorized=True,origin=True):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Host':'localhost:'+str(self.server.server_port),'Content-Type':'application/json'}
        if authorized:headers['Cookie']='canvas_auth='+canvas.task_capability('test-secret',canvas.key(self.thread))
        if origin:headers['Origin']='http://localhost:'+str(self.server.server_port)
        conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();result=(response.status,response.read());conn.close();return result
    def test_board_writes_need_both_task_cookie_and_origin(self):
        data={'kind':'board','elements':[board.text_element('http-note','Browser note',0,0)],'files':{},'base_versions':{}}
        self.assertEqual(self.request(self.route+'/events',data,authorized=False)[0],403)
        self.assertEqual(self.request(self.route+'/events',data,origin=False)[0],403)
        self.assertEqual(self.request(self.route+'/events',data)[0],200)
        data['elements'][0]['text']='Stale edit';self.assertEqual(self.request(self.route+'/events',data)[0],409)
    def test_assets_cannot_escape_bundle_and_archives_need_auth(self):
        self.assertEqual(self.request('/board-assets/../canvas.py')[0],404)
        self.assertEqual(self.request(self.route+'/archive',authorized=False)[0],403)
        self.assertEqual(self.request(self.route+'/archive')[0],200)
        self.assertEqual(self.request(self.route+'/board.excalidraw')[0],200)

class BundledEditorTests(unittest.TestCase):
    def test_shell_references_present_local_scripts_and_styles(self):
        import re
        shell=(canvas.HERE/'index.html').read_text()
        assets=re.findall(r'(?:src|href)="(/board-assets/[^\"]+)"',shell)
        self.assertGreaterEqual(len(assets),2)
        for asset in assets:
            with self.subTest(asset=asset):self.assertTrue((canvas.HERE/asset.lstrip('/')).is_file())
        self.assertTrue((canvas.HERE/'board-assets/fonts').is_dir())
        self.assertTrue((canvas.HERE/'board-assets/licenses').is_dir())

class LayoutRegressionTests(unittest.TestCase):
    def state(self):
        return {'content':{'sections':[{'id':'flow','title':'A process','blocks':[{'type':'timeline','items':[{'at':str(i),'label':label,'detail':''} for i,label in enumerate(['Collect evidence','Review the result','Publish the result'])]}]}]},'collaboration':{'viewport':{'width':800,'height':520}}}
    def test_native_sequence_preserves_source_and_uses_readable_font(self):
        s=self.state();board.sync_content(s);elements=s['board']['elements']
        self.assertEqual(len([e for e in elements if e['type']=='arrow']),2)
        self.assertTrue(all(e['fontFamily']==2 for e in elements if e['type']=='text'))
        self.assertIn('Collect evidence',' '.join(e.get('originalText','') for e in elements))
    def test_layout_is_compact_and_does_not_infer_again_from_its_own_geometry(self):
        s=self.state();board.sync_content(s);before=jev.source_hash(s)
        board.apply_presentation(s,{'status':'focused','focus_id':'flow','style':{'layout':'overview'}})
        self.assertEqual(before,jev.source_hash(s))
        cards=[e for e in s['board']['elements'] if e['type']=='rectangle']
        self.assertEqual(cards[0]['y'],cards[1]['y'])
        self.assertEqual(cards[1]['x']-(cards[0]['x']+cards[0]['width']),24)
    def test_resize_preserves_only_the_human_edited_node(self):
        s=self.state();board.sync_content(s)
        e=next(e for e in s['board']['elements'] if e['type']=='text');e['customData']['humanTouched']=True
        before=copy.deepcopy(s['board']['elements']);s['board']['human_revision']=1
        s['collaboration']['viewport']={'width':320,'height':480};board.sync_content(s)
        after={v['id']:v for v in s['board']['elements']}
        self.assertEqual(e,after[e['id']])
        for element in before:
            if element['customData'].get('nodeId') == e['customData']['nodeId']:
                self.assertEqual(element['x'],after[element['id']]['x'])
                self.assertEqual(element['y'],after[element['id']]['y'])
        self.assertNotEqual(before,s['board']['elements'])
    def test_jev_representation_questions_are_bounded_and_include_screen_constraints(self):
        s=self.state();board.sync_content(s);body,mapping=jev.build_request(s,{'rich_context':True});request=json.loads(body)
        self.assertIn('representation_section_0',request['questions'])
        self.assertEqual(request['state']['display_constraints']['minimum_screen_text_px'],16)
        self.assertLessEqual(len(body),jev.MAX_INPUT_BYTES)

class MeasuredLayoutTests(unittest.TestCase):
    setUp=BoardTests.setUp
    content=BoardTests.content
    def test_measured_geometry_persists_without_claiming_other_nodes(self):
        s=self.content();es=s['board']['elements'];first=copy.deepcopy(es[1]);first['text']='Human correction'
        rendered=copy.deepcopy(es);rendered[0]['height']-=10
        result=board.update(self.root,self.thread,{'elements':[first],'rendered':rendered,'base_versions':s['board']['versions']})['board']
        card=next(e for e in result['elements'] if e['id']==rendered[0]['id'])
        self.assertEqual(card['height'],rendered[0]['height']);self.assertFalse(card['customData'].get('humanTouched'))
    def test_measurement_cannot_replace_words(self):
        s=self.content();es=copy.deepcopy(s['board']['elements']);es[1]['text']='Replacement content'
        with self.assertRaises(ValueError):board.update(self.root,self.thread,{'elements':[],'rendered':es,'base_versions':s['board']['versions']})
