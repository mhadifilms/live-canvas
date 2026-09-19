"""Compact native board projection. No inference or changes to human-owned objects."""
import hashlib
import json
import secrets

VERSION = 3


def project(state, presentation=None):
    import board
    sections=state.get('content',{}).get('sections') or []
    latest=(state.get('automatic',{}).get('latest_final') or {}).get('text')
    if not sections and latest:
        sections=[{'id':'conversation-response','title':'From the conversation','blocks':[{'id':'reply','type':'text','text':latest}]}]
    scene=state.setdefault('board',{'elements':[],'files':{},'versions':{},'revision':0})
    source=hashlib.sha256(json.dumps(sections,sort_keys=True).encode()).hexdigest()
    p=presentation if presentation is not None else state.get('presentation',{})
    if not board.adaptive_enabled(state):p={}
    viewport=state.get('collaboration',{}).get('viewport',{})
    width=max(240,min(1800,viewport.get('width',960)))
    height=max(120,min(1400,viewport.get('height',640)))
    layout_hash=hashlib.sha256(json.dumps([VERSION,source,p,width,height,scene.get('human_revision',0)],sort_keys=True).encode()).hexdigest()
    if scene.get('layout_hash')==layout_hash:return
    if not board.adaptive_enabled(state) and scene.get('source_hash')==source and scene.get('layout_version')==VERSION:return
    old={e['id']:e for e in scene['elements']}
    # Moving another member of a human-edited group would still disturb their work.
    protected={e.get('customData',{}).get('sectionId') for e in old.values() if e.get('customData',{}).get('humanTouched')}
    occupied=[(e['x'],e['y'],abs(e['width']),abs(e['height'])) for e in old.values() if not e.get('isDeleted') and
              (not e.get('customData',{}).get('generatedText') or e.get('customData',{}).get('sectionId') in protected)]
    priority=p.get('priorities',{});focus=p.get('focus_id');style=p.get('style',{})
    ordered=sorted(sections,key=lambda sec:(sec['id']!=focus,{'high':0,'normal':1,'low':2}.get(priority.get(sec['id']),1)))
    columns=max(1,min(4,int((width+24)/304)))
    if style.get('layout')=='compare' and width>=620:columns=2
    card_width=min(420,(width-24*(columns-1))/columns)
    text_width=max(180,card_width-32)
    heights=[24.0]*columns;wanted={};previous={}
    color={'blue':'#426a82','sage':'#527565'}.get(style.get('emphasis'),'#343a40')
    def emit(e,sec,text,unit,heading=False):
        e['groupIds']=['unit-'+sec['id']+'-'+str(unit)]
        e['customData']={'origin':'agent','sectionId':sec['id'],'generatedText':text,'heading':heading,'projection':VERSION,'renderOrder':section_index*1000+unit}
        wanted[e['id']]=e
    for section_index,sec in enumerate(ordered):
        units=[];is_sequence=any(b.get('type')=='timeline' for b in sec['blocks']) or p.get('representations',{}).get(sec['id'])=='sequence'
        for block in sec['blocks']:
            capacity=max(60,min(300,int(text_width/(20*.68))*max(2,int((height-110)/26))))
            units.extend(board.chunks(board.block_text(block),capacity))
        if not units:units=['']
        # Bound native object count without dropping source material. Very large
        # sections use taller nodes, which readable camera views can navigate.
        max_units=max(1,min(80,(board.MAX_ELEMENTS-len(occupied))//max(4,len(sections)*4)))
        if len(units)>max_units:
            stride=(len(units)+max_units-1)//max_units
            units=['\n'.join(units[i:i+stride]) for i in range(0,len(units),stride)]
        row_y=max(heights);row_height=0
        for n,text in enumerate(units):
            key=lambda name:'agent-'+hashlib.sha256((sec['id']+':'+name).encode()).hexdigest()[:22]
            # Retain the first heading/body IDs from previous releases.
            bodyid=key('body' if n==0 else 'body-'+str(n));headid=key('heading' if n==0 else 'heading-'+str(n))
            col=n%columns if is_sequence else min(range(columns),key=lambda c:heights[c]);x=24+col*(card_width+24)
            if is_sequence and n and col==0:row_y+=row_height+24;row_height=0
            y=row_y if is_sequence else heights[col]
            wide=not is_sequence and len(text)>180 and columns>1
            unit_width=min(width,900) if wide else card_width
            if wide:x=24;y=max(heights)
            title=board.plain(sec['title'])+(' · '+str(n+1) if len(units)>1 else '')
            head=board.text_element(headid,title,x+16,y+14,True,unit_width-32)
            body=board.text_element(bodyid,text,x+16,y+head['height']+24,False,unit_width-32)
            boxheight=head['height']+body['height']+40
            # Fixed user objects are obstacles, never targets for automatic compaction.
            for _ in range(len(occupied)+1):
                hits=[r for r in occupied if x<r[0]+r[2]+16 and x+unit_width>r[0]-16 and y<r[1]+r[3]+16 and y+boxheight>r[1]-16]
                if not hits:break
                y=max(r[1]+r[3] for r in hits)+24
            head.update(y=y+14,strokeColor=color);body['y']=y+head['height']+24
            frame=board.base_element(key('card-'+str(n)),'rectangle',x,y,unit_width,boxheight)
            frame.update(roughness=1,roundness={'type':3},strokeColor='#adb5bd',backgroundColor='transparent')
            emit(frame,sec,'card:'+text,n)
            frame['customData'].update(sequence=is_sequence,wide=wide)
            emit(head,sec,title,n,True);emit(body,sec,text,n)
            if is_sequence and sec['id'] in previous:
                before=previous[sec['id']]
                same_row=before['y']==y
                start=(before['x']+before['width'],before['y']+before['height']/2) if same_row else (before['x']+before['width']/2,before['y']+before['height'])
                end=(x,y+boxheight/2) if same_row else (x+card_width/2,y)
                arrow=board.base_element(key('arrow-'+str(n)),'arrow',start[0],start[1],end[0]-start[0],end[1]-start[1])
                arrow.update(points=[[0,0],[end[0]-start[0],end[1]-start[1]]],startBinding=None,endBinding=None,startArrowhead=None,endArrowhead='arrow',roughness=1)
                emit(arrow,sec,'sequence:'+text,n)
                arrow['customData'].update(startCard=before['id'],endCard=frame['id'])
            previous[sec['id']]={**frame,'column':col};heights[col]=y+boxheight+24
            row_height=max(row_height,boxheight)
            if wide:heights=[max(heights)]*columns
        # Unused columns remain available to supporting ideas.
    changed=False
    for eid,e in wanted.items():
        prior=old.get(eid);sec=e['customData']['sectionId']
        if sec in protected:
            # Leave the whole existing section alone, including deleted objects.
            if prior:continue
            if any(v.get('customData',{}).get('sectionId')==sec for v in old.values()):continue
        if prior:
            comparison=lambda item:{k:v for k,v in item.items() if k not in {'version','versionNonce','updated'}}
            if comparison(prior)==comparison(e):continue
            e.update(version=prior.get('version',1)+1,versionNonce=secrets.randbelow(2**30))
        old[eid]=e;scene['versions'][eid]=scene['versions'].get(eid,0)+1;changed=True
    for eid,e in list(old.items()):
        meta=e.get('customData',{})
        if meta.get('origin')=='agent' and 'generatedText' in meta and eid not in wanted and meta.get('sectionId') not in protected and not e.get('isDeleted'):
            old[eid]={**e,'isDeleted':True,'version':e.get('version',1)+1};scene['versions'][eid]=scene['versions'].get(eid,0)+1;changed=True
    scene.update(source_hash=source,layout_hash=layout_hash,layout_version=VERSION)
    if changed:scene['elements']=list(old.values());scene['revision']+=1;scene['last_actor']='jev' if p else 'agent'
