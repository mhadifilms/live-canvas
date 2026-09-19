import copy
import json
import unittest

import board
import canvas
import typesafe_presentation as jev
from board_model import compile_model, validate_graph
import test_board as fixtures


def graph():
    return {'id':'argument','type':'graph','nodes':[
        {'id':'claim','role':'claim','label':'A shared board helps','detail':'The board and chat share context.'},
        {'id':'evidence','role':'evidence','label':'Edits survive','detail':'Human wording is preserved.'},
        {'id':'question','role':'question','label':'What changes next?'}],
        'edges':[{'id':'support','from':'evidence','to':'claim','relation':'supports'},
                 {'id':'next','from':'claim','to':'question','relation':'connects'}]}


def sections(block=None):
    return [{'id':'work','title':'Working together','blocks':[block or graph()]}]


class SemanticModelTests(unittest.TestCase):
    def test_stable_graph_identity_survives_reordering_and_rewording(self):
        before=compile_model(sections());block=graph();block['nodes'].reverse();block['nodes'][0]['label']='A new wording'
        after=compile_model(sections(block),before)
        self.assertEqual({n['sourceId']:n['id'] for n in before['nodes']},{n['sourceId']:n['id'] for n in after['nodes']})
        self.assertEqual(before['edges'],after['edges'])
    def test_legacy_insertion_does_not_change_existing_identity(self):
        block={'id':'ideas','type':'list','items':['One','Two','Three']};before=compile_model(sections(block))
        block['items'].insert(0,'New');after=compile_model(sections(block),before)
        self.assertEqual([n['id'] for n in before['nodes']],[n['id'] for n in after['nodes']][1:])
    def test_legacy_edit_keeps_identity_and_independent_items_have_no_edges(self):
        block={'id':'ideas','type':'list','items':['One','Two']};before=compile_model(sections(block))
        block['items'][0]='Updated';after=compile_model(sections(block),before)
        self.assertEqual(before['nodes'][0]['id'],after['nodes'][0]['id']);self.assertEqual(after['edges'],[])
    def test_graph_rejects_bad_relationships_and_sources(self):
        variants=[]
        b=graph();b['edges'][0]['to']='missing';variants.append(b)
        b=graph();b['nodes'][0]['source']='javascript:alert(1)';variants.append(b)
        b=graph();b['nodes'][1]['id']='claim';variants.append(b)
        b=graph();b['edges'][0]['relation']='invented';variants.append(b)
        b=graph();b['nodes'][0]['role']=[];variants.append(b)
        for b in variants:
            with self.subTest(b=b),self.assertRaises(ValueError):validate_graph(b)
    def test_valid_graph_schema_and_context_include_semantics(self):
        canvas.validate_sections(sections());s={'content':{'sections':sections()}};board.sync_content(s)
        self.assertTrue(any(e.get('role')=='claim' for e in board.context(s)))
        self.assertTrue(any(e.get('relation')=='supports' for e in board.context(s)))
    def test_edges_have_native_and_reciprocal_bindings(self):
        s={'content':{'sections':sections()}};board.sync_content(s);es={e['id']:e for e in s['board']['elements']}
        for e in es.values():
            if e['type']=='arrow':
                for side in ('startBinding','endBinding'):
                    target=es[e[side]['elementId']]
                    self.assertIn({'id':e['id'],'type':'arrow'},target['boundElements'])
    def test_jev_request_contains_roles_and_relations_and_stays_bounded(self):
        s={'content':{'sections':sections()}};board.sync_content(s);body,_=jev.build_request(s,{'rich_context':True});req=json.loads(body)
        self.assertIn('map',req['questions']['representation_section_0']['criteria'])
        self.assertIn(b'supports',body);self.assertIn(b'evidence',body);self.assertLessEqual(len(body),jev.MAX_INPUT_BYTES)


class SemanticOwnershipTests(unittest.TestCase):
    setUp=fixtures.BoardTests.setUp
    current=fixtures.BoardTests.current
    def content(self,block=None):
        return canvas.update_content(self.root,self.thread,{'sections':sections(block)})
    def test_text_edit_preserves_words_but_other_nodes_keep_updating(self):
        s=self.content();scene=s['board'];e=copy.deepcopy(next(e for e in scene['elements'] if e['customData'].get('part')=='body' and e['originalText']))
        e['text']='My correction';e['height']+=26
        saved=board.update(self.root,self.thread,{'elements':[e],'rendered':scene['elements'],'base_versions':scene['versions']})['board']
        owned=next(v for v in saved['elements'] if v['id']==e['id'])
        self.assertEqual(owned['originalText'],'My correction');self.assertNotIn('height',owned['customData']['humanFields'])
        block=graph();block['nodes'][0]['detail']='Agent rewrite';block['nodes'][1]['label']='New evidence'
        updated=self.content(block)['board'];byid={v['id']:v for v in updated['elements']}
        self.assertEqual(byid[e['id']]['text'],'My correction')
        self.assertTrue(any(v.get('originalText')=='New evidence' for v in updated['elements']))
        self.assertFalse(byid[e['id']]['customData']['pinned'])
    def test_measured_position_is_not_mistaken_for_a_human_move(self):
        scene=self.content()['board'];rendered=copy.deepcopy(scene['elements'])
        for e in rendered:e['y']+=100
        target=copy.deepcopy(next(e for e in rendered if e['customData'].get('part')=='heading'));target['text']='A correction'
        result=board.update(self.root,self.thread,{'elements':[target],'rendered':rendered,'base_versions':scene['versions']})['board']
        e=next(e for e in result['elements'] if e['id']==target['id'])
        self.assertFalse(e['customData']['pinned']);self.assertNotIn('y',e['customData']['humanFields'])
    def test_moving_a_node_does_not_freeze_its_neighbors(self):
        scene=self.content()['board'];e=copy.deepcopy(scene['elements'][0]);e['x']=900
        board.update(self.root,self.thread,{'elements':[e],'base_versions':scene['versions']})
        block=graph();block['nodes'][1]['label']='Another updated neighbor'
        result=self.content(block)['board'];fixed=next(v for v in result['elements'] if v['id']==e['id'])
        self.assertEqual(fixed['x'],900);self.assertTrue(fixed['customData']['pinned'])
        self.assertTrue(any(v.get('originalText')=='Another updated neighbor' for v in result['elements']))
    def test_deleted_node_card_stays_deleted_and_edges_are_retired(self):
        scene=self.content()['board'];e={**scene['elements'][0],'isDeleted':True}
        board.update(self.root,self.thread,{'elements':[e],'base_versions':scene['versions']})
        result=self.content()['board'];self.assertTrue(next(v for v in result['elements'] if v['id']==e['id'])['isDeleted'])
        self.assertFalse(any(v['type']=='arrow' and not v['isDeleted'] and any((v.get(k) or {}).get('elementId')==e['id'] for k in ('startBinding','endBinding')) for v in result['elements']))
    def test_adaptation_off_does_not_rearrange_existing_nodes_on_content_edit(self):
        import collaboration
        scene=self.content()['board'];before={e['id']:(e['x'],e['y'],e['width'],e['height']) for e in scene['elements'] if e['type']!='arrow'}
        collaboration.submit(self.root,self.thread,{'kind':'preference','id':'off','text':'adaptive:off'})
        block=graph();block['nodes'].reverse();block['nodes'][0]['label']='Changed while off'
        result=self.content(block)['board']
        for e in result['elements']:
            if e['id'] in before and not e['customData'].get('edgeLabel'):self.assertEqual(before[e['id']],(e['x'],e['y'],e['width'],e['height']))
    def test_removed_source_retains_human_work_without_retaining_unrelated_nodes(self):
        scene=self.content()['board'];e={**scene['elements'][1],'text':'Keep my note'}
        board.update(self.root,self.thread,{'elements':[e],'base_versions':scene['versions']})
        result=canvas.update_content(self.root,self.thread,{'sections':[]})['board']
        self.assertTrue(any(v.get('text')=='Keep my note' for v in result['elements']))
        self.assertLessEqual(len([v for v in result['elements'] if not v.get('isDeleted')]),3)

class SemanticBoundaryTests(unittest.TestCase):
    def test_context_changes_do_not_reuse_previous_object_identity(self):
        before=compile_model(sections(),namespace='first')
        after=compile_model(sections(),before,namespace='second')
        self.assertFalse({n['id'] for n in before['nodes']} & {n['id'] for n in after['nodes']})
    def test_large_requests_keep_a_usable_bounded_candidate_set(self):
        s={'content':{'sections':[{'id':str(i),'title':'Graph','blocks':[graph()]} for i in range(8)]}}
        body,mapping=jev.build_request(s,{'rich_context':True})
        request=json.loads(body)
        self.assertLessEqual(len(body),jev.MAX_INPUT_BYTES);self.assertGreater(len(mapping),0)
        self.assertEqual(request['state']['total_sections'],8)
        self.assertEqual(set(mapping),{c['option'] for c in request['state']['candidates']})
        self.assertEqual(set(request['questions']['presentation']['criteria']),set(mapping)|{'unchanged'})

class DerivedBindingTests(unittest.TestCase):
    setUp=fixtures.BoardTests.setUp
    current=fixtures.BoardTests.current
    def test_native_connector_motion_does_not_claim_its_layout(self):
        s=canvas.update_content(self.root,self.thread,{'sections':sections()});scene=s['board']
        arrow=copy.deepcopy(next(e for e in scene['elements'] if e['type']=='arrow'))
        shape=copy.deepcopy(next(e for e in scene['elements'] if e['id']==arrow['endBinding']['elementId']))
        shape['x']+=40;arrow['width']+=40;arrow['points'][-1][0]+=40
        result=board.update(self.root,self.thread,{'elements':[shape,arrow],'rendered':scene['elements'],'base_versions':scene['versions']})['board']
        target=next(e for e in result['elements'] if e['id']==arrow['id'])
        self.assertFalse(target['customData'].get('humanTouched'))
        self.assertTrue(next(e for e in result['elements'] if e['id']==shape['id'])['customData']['pinned'])

class LayoutPolicyTests(unittest.TestCase):
    def test_off_and_density_changes_advance_scene_revision(self):
        s={'content':{'sections':sections()}};board.sync_content(s);before=s['board']['revision']
        s['collaboration']={'events':[{'kind':'preference','text':'adaptive:off'}]};board.sync_content(s)
        self.assertFalse(s['board']['adaptive']);self.assertGreater(s['board']['revision'],before)
        s['collaboration']={};board.sync_content(s);before=s['board']['revision']
        board.apply_presentation(s,{'status':'unchanged','style':{'density':'comfortable'}})
        self.assertEqual(s['board']['layout']['gap'],32);self.assertGreater(s['board']['revision'],before)
