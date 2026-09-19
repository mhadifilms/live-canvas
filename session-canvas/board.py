"""Shared Excalidraw scene. Element-level optimistic concurrency prevents lost edits."""
import copy
import hashlib
import html
import json
import math
import re
import secrets
import time

TYPES = {'rectangle','diamond','ellipse','line','arrow','freedraw','text','image','frame','magicframe','embeddable'}
MAX_ELEMENTS = 2000
MAX_SCENE = 8 * 1024 * 1024

class Conflict(ValueError): pass


def identity(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value))


def validate(elements, files):
    if not isinstance(elements,list) or len(elements)>MAX_ELEMENTS or not isinstance(files,dict): raise ValueError('Board limits exceeded')
    if len(json.dumps([elements,files]).encode())>MAX_SCENE: raise ValueError('Board exceeds 8 MiB')
    ids=set()
    for e in elements:
        if not isinstance(e,dict) or not identity(e.get('id')) or e['id'] in ids or e.get('type') not in TYPES: raise ValueError('Invalid board element')
        ids.add(e['id'])
        if any(k not in e for k in ('x','y','width','height')):raise ValueError('Missing object geometry')
        for k in ('version','versionNonce'):
            if k in e and (type(e[k]) is not int or not 0 <= e[k] < 2**53):raise ValueError('Invalid editor version')
        for k in ('x','y','width','height','angle','fontSize','lineHeight','strokeWidth','opacity'):
            v=e.get(k,0)
            if type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1000000: raise ValueError('Invalid element coordinates')
        if not isinstance(e.get('customData',{}),dict): raise ValueError('Invalid metadata')
        for k in ('strokeColor','backgroundColor'):
            if not isinstance(e.get(k,''),str) or len(e.get(k,''))>80 or not re.fullmatch(r'(#[A-Fa-f0-9]{3,8}|transparent|[a-zA-Z]+)',e.get(k,'transparent')): raise ValueError('Invalid color')
        points=e.get('points',[])
        if not isinstance(points,list) or len(points)>20000 or any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1000000 for v in p) for p in points): raise ValueError('Invalid points')
        if e.get('type')=='text' and (not isinstance(e.get('text'),str) or len(e['text'])>50000): raise ValueError('Invalid board text')
        if e.get('type')=='embeddable': raise ValueError('Remote embedded websites are not supported in private boards')
        if e.get('link') and not re.match(r'^(https?://|mailto:)',str(e['link'])): raise ValueError('Unsupported board link')
    total=0
    for fid,f in files.items():
        if not identity(fid) or not isinstance(f,dict) or f.get('mimeType') not in {'image/png','image/jpeg','image/webp','image/gif'}: raise ValueError('Unsupported image')
        data=f.get('dataURL','')
        if not isinstance(data,str) or not data.startswith('data:'+f['mimeType']+';base64,') or len(data)>3*1024*1024: raise ValueError('Invalid or oversized image')
        import base64,binascii
        try: base64.b64decode(data.split(',',1)[1],validate=True)
        except (ValueError,binascii.Error): raise ValueError('Invalid image data') from None
        total+=len(data)
    if total>6*1024*1024: raise ValueError('Board images exceed 6 MiB; keep other files as attachments')


def base_element(eid, kind, x, y, width, height):
    return {'id':eid,'type':kind,'x':x,'y':y,'width':width,'height':height,'angle':0,
        'strokeColor':'#343a40','backgroundColor':'transparent','fillStyle':'solid','strokeWidth':1,
        'strokeStyle':'solid','roughness':0,'opacity':100,'groupIds':[],'frameId':None,'roundness':None,
        'seed':int(hashlib.sha256(eid.encode()).hexdigest()[:7],16),'version':1,'versionNonce':1,
        'isDeleted':False,'boundElements':None,'updated':int(time.time()*1000),'link':None,'locked':False}


def plain(value):
    return re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',str(value or '')).replace('**','').replace('`','')


def block_text(block):
    kind=block.get('type')
    if kind=='text':return plain(block.get('text'))
    if kind=='table':return '\n'.join('  |  '.join(row) for row in [block['columns'],*block['rows']])
    lines=[]
    for v in block.get('items',[]):
        if isinstance(v,str):lines.append('• '+plain(v))
        elif kind=='reveal':lines.append(plain(v.get('prompt'))+'\n'+plain(v.get('answer')))
        elif kind=='checklist':lines.append(('☑ ' if v.get('checked') else '☐ ')+plain(v.get('text')))
        else:lines.append(' — '.join(plain(v.get(k)) for k in ('at','label','detail') if v.get(k)))
    return '\n'.join(lines)


def text_element(eid,text,x,y,heading=False,width=320):
    import textwrap
    size=24 if heading else 20
    lines=[]
    # Conservative server fallback. The editor measures with the loaded font.
    for line in text.split('\n'):
        lines.extend(textwrap.wrap(line,width=max(8,int(width/(size*.68))),replace_whitespace=False) or [''])
    wrapped='\n'.join(lines)
    e=base_element(eid,'text',x,y,width,max(size*1.3,len(lines)*size*1.3))
    e.update(text=wrapped,originalText=text,fontSize=size,fontFamily=2,textAlign='left',verticalAlign='top',containerId=None,autoResize=False,lineHeight=1.3)
    return e


def chunks(text, limit=300):
    """Keep every source word; split dense prose into readable board-sized units."""
    import textwrap
    return [piece for paragraph in text.split('\n') if paragraph.strip()
            for piece in textwrap.wrap(paragraph,limit,break_long_words=True,break_on_hyphens=False)]


def sync_content(state):
    from board_layout import project
    project(state)


def update(root,thread,payload,actor='human'):
    import canvas
    incoming=payload.get('elements',[]);files=payload.get('files',{});bases=payload.get('base_versions',{})
    validate(incoming,files)
    rendered=payload.get('rendered',[])
    validate(rendered,{})
    if not isinstance(bases,dict):raise ValueError('Expected base element versions')
    def apply(state):
        scene=state.setdefault('board',{'elements':[],'files':{},'versions':{},'revision':0})
        current={e['id']:e for e in scene['elements']}
        changed=[]
        incoming_ids={e['id'] for e in incoming}
        for measured in rendered:
            eid=measured['id'];old=current.get(eid)
            if eid in incoming_ids or not old or not old.get('customData',{}).get('projection') or old.get('customData',{}).get('humanTouched'):continue
            # Accept derived geometry and line breaks only, never different words or ownership.
            if re.sub(r'\s','',measured.get('text','')) != re.sub(r'\s','',old.get('text','')):raise ValueError('Measured layout cannot change content')
            geometry={k:measured[k] for k in ('x','y','width','height','text','points') if k in measured}
            if all(old.get(k)==v for k,v in geometry.items()):continue
            if bases.get(eid,0)!=scene['versions'].get(eid,0):raise Conflict('The board changed while its layout was measured')
            current[eid]={**old,**geometry,'version':old.get('version',1)+1};changed.append(eid)
        for element in incoming:
            eid=element['id'];old=current.get(eid)
            # Ignore our own server-owned metadata when comparing a round trip.
            comparable=lambda e:{k:v for k,v in e.items() if k not in {'customData','version','versionNonce','updated','index','seed'}}
            if old and comparable(old)==comparable(element):continue
            if bases.get(eid,0)!=scene['versions'].get(eid,0):raise Conflict('This object changed elsewhere. Your local changes are kept; reload or export before resolving.')
            e=copy.deepcopy(element)
            prior=(old or {}).get('customData',{})
            # Browsers cannot reset the ownership/protection of generated content.
            e['customData']={**e.get('customData',{}),**prior,'lastActor':actor}
            if actor=='human':e['customData']['humanTouched']=True
            current[eid]=e;changed.append(eid)
        if not changed and all(scene.get('files',{}).get(k)==v for k,v in files.items()):return False
        for fid,f in files.items():
            if fid in scene.get('files',{}) and scene['files'][fid].get('dataURL')!=f.get('dataURL'):raise Conflict('An image changed elsewhere')
        combined_files={**scene.get('files',{}),**files};validate(list(current.values()),combined_files)
        scene['elements']=list(current.values());scene['files']=combined_files
        for eid in changed:scene['versions'][eid]=scene['versions'].get(eid,0)+1
        scene['revision']+=1;scene['last_actor']=actor
        if actor=='human':
            scene['human_revision']=scene.get('human_revision',0)+1
        state.pop('presentation',None)
    state=canvas.mutate(root,thread,apply)
    return {'saved':True,'board':state['board'],'revision':state['revision']}


def context(state):
    result=[]
    for e in state.get('board',{}).get('elements',[]):
        if e.get('isDeleted'):continue
        result.append({k:e[k] for k in ('id','type','text','x','y','width','height') if k in e})
    return result


def svg(state):
    scene=state.get('board',{});elements=[e for e in scene.get('elements',[]) if not e.get('isDeleted')]
    if not elements:return ''
    x=min(e['x'] for e in elements)-30;y=min(e['y'] for e in elements)-30
    width=max(e['x']+abs(e['width']) for e in elements)-x+30;height=max(e['y']+abs(e['height']) for e in elements)-y+30
    esc=lambda v:html.escape(str(v),quote=True)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {width} {height}" role="img" aria-label="Saved shared board">']
    for e in elements:
        stroke=esc(e.get('strokeColor','#333'));fill=esc(e.get('backgroundColor','transparent'));w=e['width'];h=e['height']
        out.append(f'<g transform="translate({e["x"]} {e["y"]}) rotate({e.get("angle",0)*180/math.pi} {w/2} {h/2})" opacity="{min(100,max(0,e.get("opacity",100)))/100}">')
        kind=e['type']
        if kind=='text':
            size=e.get('fontSize',18)
            for i,line in enumerate(e.get('text','').split('\n')):out.append(f'<text x="0" y="{(i+1)*size*e.get("lineHeight",1.25)}" fill="{stroke}" font-family="system-ui,sans-serif" font-size="{size}">{esc(line)}</text>')
        elif kind=='ellipse':out.append(f'<ellipse cx="{w/2}" cy="{h/2}" rx="{abs(w)/2}" ry="{abs(h)/2}" stroke="{stroke}" fill="{fill}"/>')
        elif kind in {'freedraw','line','arrow'}:
            points=' '.join(f'{p[0]},{p[1]}' for p in e.get('points',[]))
            out.append(f'<polyline points="{esc(points)}" stroke="{stroke}" fill="none" stroke-width="{e.get("strokeWidth",2)}"/>')
        elif kind=='image' and e.get('fileId') in scene.get('files',{}):out.append(f'<image width="{w}" height="{h}" href="{esc(scene["files"][e["fileId"]]["dataURL"])}"/>')
        else:out.append(f'<rect width="{abs(w)}" height="{abs(h)}" stroke="{stroke}" fill="{fill}"/>')
        out.append('</g>')
    return ''.join(out)+'</svg>'


def adaptive_enabled(state):
    choices=[e.get('text') for e in state.get('collaboration',{}).get('events',[]) if e.get('kind')=='preference' and e.get('text') in {'adaptive:on','adaptive:off'}]
    return not choices or choices[-1]=='adaptive:on'


def apply_presentation(state,presentation):
    """Semantic decisions guide native scene projection; human objects stay fixed."""
    if not adaptive_enabled(state) or presentation.get('status') not in {'focused','unchanged','uncertain'}:return
    from board_layout import project
    project(state,presentation)


def feedback(state):
    objects=[e for e in state.get('board',{}).get('elements',[]) if e.get('customData',{}).get('humanTouched') and not e.get('isDeleted')]
    return [{'id':e['id'],'kind':e['type'],'text':e.get('text','')[:240]} for e in sorted(objects,key=lambda e:e.get('updated',0))[-5:]]
