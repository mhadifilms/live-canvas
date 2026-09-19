// Screen geometry stays deterministic and local. Jev chooses meaning, never pixels.
export const MIN_TEXT_PX = 16;
export function bounds(elements) {
  if (!elements.length) return {x:0,y:0,width:1,height:1};
  const boxes=elements.map(e=>{
    const w=Math.abs(e.width),h=Math.abs(e.height),a=e.angle||0;
    const rw=Math.abs(w*Math.cos(a))+Math.abs(h*Math.sin(a));
    const rh=Math.abs(w*Math.sin(a))+Math.abs(h*Math.cos(a));
    return {x:e.x+e.width/2-rw/2,y:e.y+e.height/2-rh/2,width:rw,height:rh};
  });
  const x=Math.min(...boxes.map(b=>b.x)),y=Math.min(...boxes.map(b=>b.y));
  return {x,y,width:Math.max(1,...boxes.map(b=>b.x+b.width-x)),height:Math.max(1,...boxes.map(b=>b.y+b.height-y))};
}
export function safeViewport(editor) {
  const r=editor.getBoundingClientRect();
  let left=20,top=84,right=20,bottom=64;
  for (const el of editor.querySelectorAll('.App-toolbar, .HintViewer, .layer-ui__wrapper__footer, .App-menu_bottom, .sidebar, .App-menu__left')) {
    const b=el.getBoundingClientRect();
    if (!b.width || !b.height) continue;
    if (el.matches('.App-toolbar, .HintViewer')) {
      if(b.top < r.top+r.height/2) top=Math.max(top,b.bottom-r.top+16);
      else bottom=Math.max(bottom,r.bottom-b.top+16);
    }
    else if (el.matches('.sidebar')) right=Math.max(right,r.right-b.left+16);
    else if (el.matches('.App-menu__left')) left=Math.max(left,b.right-r.left+16);
    else bottom=Math.max(bottom,r.bottom-b.top+16);
  }
  return {x:left,y:top,width:Math.max(1,r.width-left-right),height:Math.max(1,r.height-top-bottom)};
}
export function wrapText(text,width,measure) {
  const lines=[];
  for (const paragraph of text.split('\n')) {
    let line='';
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      if (line && measure(line+' '+word)>width) { lines.push(line);line=''; }
      let part='';
      for (const char of word) {
        if (part && measure(part+char)>width) { if(line){lines.push(line);line='';} lines.push(part);part=''; }
        part+=char;
      }
      line+=(line?' ':'')+part;
    }
    lines.push(line);
  }
  return lines.join('\n');
}
export function prepareScene(scene,measure) {
  const elements=(scene.elements||[]).map(e=>{
    if(e.isDeleted || e.type!=='text' || !e.customData?.projection || e.customData?.humanTouched) return {...e};
    const text=wrapText(e.originalText||e.text,Math.max(80,e.width-4),s=>measure(s,e));
    return {...e,text,height:text.split('\n').length*e.fontSize*e.lineHeight};
  });
  // Recompute cards from measured text; preserve protected sections and authored diagrams.
  const protectedSections=new Set(elements.filter(e=>e.customData?.humanTouched).map(e=>e.customData?.sectionId));
  const groups=new Map();
  for (const e of elements) if(!e.isDeleted&&e.customData?.projection&&!protectedSections.has(e.customData.sectionId)) {
    const key=e.groupIds[0];if(!groups.has(key))groups.set(key,[]);groups.get(key).push(e);
  }
  const orderedGroups=[...groups.values()].sort((a,b)=>(a[0].customData?.renderOrder||0)-(b[0].customData?.renderOrder||0));
  const cards=orderedGroups.map(g=>g.find(e=>e.type==='rectangle')).filter(Boolean);
  const columns=[...new Set(cards.map(e=>e.x))].sort((a,b)=>a-b);
  const bottoms=new Map(columns.map(x=>[x,24]));
  const fixed=elements.filter(e=>!e.isDeleted&&(!e.customData?.projection||protectedSections.has(e.customData.sectionId)));
  let sequenceRowY=24;
  for (const objects of orderedGroups) {
    const card=objects.find(e=>e.type==='rectangle'),head=objects.find(e=>e.type==='text'&&e.customData.heading),body=objects.find(e=>e.type==='text'&&!e.customData.heading);
    if (!card||!head||!body) continue;
    const oldX=card.x;
    const x=card.customData.wide?columns[0]:card.customData.sequence?oldX:columns.reduce((a,b)=>bottoms.get(a)<=bottoms.get(b)?a:b);
    let y=card.customData.wide?Math.max(...bottoms.values()):bottoms.get(x)||24;
    if(card.customData.sequence) {
      if(x===columns[0])sequenceRowY=Math.max(...bottoms.values());
      y=sequenceRowY;
    }
    const height=head.height+body.height+40;
    for(let tries=0;tries<=fixed.length;tries++) {
      const hits=fixed.filter(e=>x<e.x+Math.abs(e.width)+16&&x+card.width>e.x-16&&y<e.y+Math.abs(e.height)+16&&y+height>e.y-16);
      if(!hits.length)break;
      y=Math.max(...hits.map(e=>e.y+Math.abs(e.height)))+24;
    }
    card.x=x;card.y=y;card.height=height;
    head.x=x+16;head.y=y+14;body.x=x+16;body.y=head.y+head.height+10;
    if(card.customData.wide) for(const c of columns)bottoms.set(c,y+height+24);
    else bottoms.set(x,y+height+24);
  }
  const byId=new Map(elements.map(e=>[e.id,e]));
  for (const e of elements) if(e.type==='arrow'&&e.customData?.startCard&&!e.customData?.humanTouched) {
    const a=byId.get(e.customData.startCard),b=byId.get(e.customData.endCard);
    if(a&&b&&!protectedSections.has(e.customData.sectionId)) {
      const across=b.x>a.x;
      e.x=across?a.x+a.width:a.x+a.width/2;e.y=across?a.y+a.height/2:a.y+a.height;
      e.width=(across?b.x:b.x+b.width/2)-e.x;e.height=(across?b.y+b.height/2:b.y)-e.y;
      e.points=across?[[0,0],[e.width,e.height]]:[[0,0],[0,e.height/2],[e.width,e.height/2],[e.width,e.height]];
    }
  }
  return {...scene,elements};
}
export function readableViews(elements,rect) {
  const visible=elements.filter(e=>!e.isDeleted);
  if(!visible.length)return [];
  const floor=group=>Math.max(.5,...group.filter(e=>e.type==='text').map(e=>MIN_TEXT_PX/Math.max(1,e.fontSize)));
  const fits=group=>{const b=bounds(group);return Math.min(rect.width/b.width,rect.height/b.height)>=floor(group);};
  if(fits(visible))return [{...bounds(visible),zoom:Math.min(1.15,rect.width/bounds(visible).width,rect.height/bounds(visible).height)}];
  const groups=new Map();
  for(const e of visible){const id=e.groupIds?.[0]||e.id;if(!groups.has(id))groups.set(id,[]);groups.get(id).push(e);}
  const pages=[];let batch=[];
  function add(group) {
    const b=bounds(group),z=Math.max(floor(group),Math.min(1,rect.width/b.width,rect.height/b.height));
    const w=rect.width/z,h=rect.height/z;
    // Oversized human diagrams remain intact; readable camera tiles expose every part.
    for(let y=b.y;y<b.y+b.height;y+=h*.9) for(let x=b.x;x<b.x+b.width;x+=w*.9) {
      pages.push({x,y,width:Math.min(w,b.x+b.width-x),height:Math.min(h,b.y+b.height-y),zoom:z});
      if(x+w>=b.x+b.width)break;
    }
  }
  for(const group of groups.values()) {
    if(batch.length&&!fits([...batch,...group])){add(batch);batch=[];}
    batch.push(...group);
  }
  if(batch.length)add(batch);
  return pages;
}
export function camera(view,rect) {
  const zoom=view.zoom;
  return {zoom:{value:zoom},scrollX:(rect.x+(rect.width-view.width*zoom)/2)/zoom-view.x,scrollY:(rect.y+(rect.height-view.height*zoom)/2)/zoom-view.y};
}
