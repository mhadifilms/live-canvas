import test from 'node:test';
import assert from 'node:assert/strict';
import {safeViewport,bounds,camera,readableViews,wrapText,prepareScene} from './layout.mjs';
const text=(id,x,y,w,h)=>({id,type:'text',x,y,width:w,height:h,fontSize:20,text:'Work',groupIds:[id]});
test('readable fit clears toolbar, footer and side padding',()=>{
 const elements=[text('a',10,20,400,240)];const rect={x:24,y:96,width:480,height:440};
 const view=readableViews(elements,rect)[0],c=camera(view,rect),b=bounds(elements),z=c.zoom.value;
 assert.ok((b.x+c.scrollX)*z>=rect.x);
 assert.ok((b.y+c.scrollY)*z>=rect.y);
 assert.ok((b.x+b.width+c.scrollX)*z<=rect.x+rect.width+.01);
 assert.ok((b.y+b.height+c.scrollY)*z<=rect.y+rect.height+.01);
 assert.ok(z*20>=16);
});
test('dense board gets readable views rather than tiny all-content zoom',()=>{
 const es=Array.from({length:12},(_,i)=>text('n'+i,(i%3)*350,Math.floor(i/3)*280,320,250));
 const views=readableViews(es,{x:16,y:90,width:330,height:430});
 assert.ok(views.length>1);assert.ok(views.every(v=>v.zoom*20>=16));
});
test('long human text has reachable camera tiles without modifying the text',()=>{
 const e=text('a',0,0,500,2500),before=JSON.stringify(e);
 const views=readableViews([e],{x:20,y:90,width:500,height:400});
 assert.ok(views.length>1);assert.equal(JSON.stringify(e),before);
 assert.ok(views.at(-1).y+views.at(-1).height>=2500);
});
test('pixel wrapping includes wide glyphs and unbroken words without losing source',()=>{
 const source='WWW WWW long_unbroken_path_1234567890';const width=s=>[...s].reduce((n,c)=>n+(c==='W'?20:8),0);
 const wrapped=wrapText(source,72,width);
 assert.ok(wrapped.split('\n').every(s=>width(s)<=72));
 assert.equal(wrapped.replace(/\s/g,''),source.replace(/\s/g,''));
});
test('font repair does not mutate the server baseline or claim human work',()=>{
 const e={...text('a',20,30,80,120),text:'WWW WWW',originalText:'WWW WWW',lineHeight:1.3,customData:{projection:2}};
 const human={...text('b',90,40,100,100),customData:{humanTouched:true}};
 const scene={elements:[e,human]},copy=JSON.stringify(scene);
 const result=prepareScene(scene,s=>s.length*20);
 assert.equal(JSON.stringify(scene),copy);assert.equal(result.elements[0].text,'WWW\nWWW');assert.deepEqual(result.elements[1],human);
});

test('mobile bottom toolbar is not mistaken for a top obstruction',()=>{
 const toolbar=(top,bottom)=>({getBoundingClientRect:()=>({top,bottom,left:14,right:466,width:452,height:bottom-top}),matches:s=>s.includes('.App-toolbar')});
 const editor={getBoundingClientRect:()=>({top:48,bottom:720,left:0,right:480,width:480,height:672}),querySelectorAll:()=>[toolbar(64,108),toolbar(658,706)]};
 const rect=safeViewport(editor);assert.equal(rect.y,84);assert.ok(rect.height>450);assert.ok(rect.y+rect.height<=610);
});
