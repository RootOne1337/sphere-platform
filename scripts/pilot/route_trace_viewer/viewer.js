'use strict';
(async()=>{
  const data=await fetch('timeline.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('timeline');return r.json();});
  const diagnostics=document.getElementById('diagnostics');
  if(diagnostics?.textContent){const extra=JSON.parse(diagnostics.textContent);if(extra.schemaVersion!==1||extra.sourceManifestSha256!==data.sourceManifestSha256||extra.geometrySha256!==data.geometrySha256||extra.frames.length!==data.frames.length||extra.traceTimes.length!==data.trace.length)throw Error('diagnostics_binding');extra.frames.forEach((row,i)=>{if(row.index!==data.frames[i].index||!['unknown','confirming','consistent_same_clip'].includes(row.state))throw Error('diagnostics_frame');data.frames[i].localizationCheck={state:row.state};});data.traceTimes=extra.traceTimes;data.uncertainSpans=extra.uncertainSpans;}
  const video=document.getElementById('video'),canvas=document.getElementById('overlay'),ctx=canvas.getContext('2d');
  const map=document.getElementById('map'),m=map.getContext('2d'),status=document.getElementById('status');
  const enabled=document.getElementById('enabled'),thickness=document.getElementById('thickness'),opacity=document.getElementById('opacity'),mode=document.getElementById('mode');
  const hasSurface=data.frames.some(row=>row.surfacePreview);
  mode.options[1].disabled=!hasSurface;if(hasSurface)mode.value='surface';
  canvas.width=data.width;canvas.height=data.height;
  const xs=data.trace.map(p=>p[0]),ys=data.trace.map(p=>p[1]);
  const low=[Math.min(...xs),Math.min(...ys)],high=[Math.max(...xs),Math.max(...ys)];
  const scale=440/Math.max(high[0]-low[0],high[1]-low[1],1e-6);
  let zoom=1,pan=[0,0],drag=null,lastSeconds=0;
  const xy=p=>[250+(p[0]-(low[0]+high[0])/2)*scale*zoom+pan[0],250-(p[1]-(low[1]+high[1])/2)*scale*zoom+pan[1]];
  function render(seconds){
    lastSeconds=seconds;
    let lo=0,hi=data.frames.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(data.frames[mid].seconds<=seconds+.002)lo=mid+1;else hi=mid;}
    const row=data.frames[Math.max(0,lo-1)];ctx.clearRect(0,0,canvas.width,canvas.height);
    const surface=mode.value==='surface';
    const check=row.localizationCheck,poseRejected=check?.state==='unknown';
    const segments=poseRejected?[]:surface?(row.surfacePreview?.segments??[]):row.points.slice(1).map((p,i)=>[row.points[i],p]);
    if(enabled.checked&&segments.length){ctx.beginPath();segments.forEach(pair=>{ctx.moveTo(pair[0][0]*canvas.width,pair[0][1]*canvas.height);ctx.lineTo(pair[1][0]*canvas.width,pair[1][1]*canvas.height);});ctx.lineJoin='round';ctx.lineCap='round';ctx.strokeStyle=surface?`rgba(255,225,90,${opacity.value})`:`rgba(80,236,218,${opacity.value})`;ctx.lineWidth=Number(thickness.value)*canvas.width/960;ctx.stroke();}
    m.clearRect(0,0,500,500);m.lineWidth=2;data.trace.slice(1).forEach((p,i)=>{const t0=data.traceTimes?.[i],t1=data.traceTimes?.[i+1],uncertain=(data.uncertainSpans??[]).some(span=>t0<=span[1]&&t1>=span[0]);m.strokeStyle=uncertain?'#efad68':'#567482';m.beginPath();const a=xy(data.trace[i]),b=xy(p);m.moveTo(...a);m.lineTo(...b);m.stroke();});
    if(row.mapPoint&&!poseRejected){const [x,y]=xy(row.mapPoint);m.fillStyle='#71d8ff';m.beginPath();m.arc(x,y,7,0,2*Math.PI);m.fill();}
    const reasonNames={no_local_surface_support:'Нет опоры поверхности',stopped_at_missing_surface_support:'Остановлено у пробела карты',stopped_at_surface_discontinuity:'Остановлено у скачка поверхности',candidate_not_body_or_clearance:'Локальная гипотеза поверхности',pose_unavailable:'Нет позы',surface_not_below_camera:'Плоскость не под камерой'};
    status.textContent=`Время: ${row.seconds.toFixed(2)} с\nИсходный кадр: ${row.index}\nПоза: ${row.poseSource==='reconstruction_reference_pose'?'опорная SfM':row.poseSource==='same_recording_interpolated_pose'?'интерполяция записи':'нет привязки'}\nОтрезков линии: ${segments.length}\nГоризонт: ${(surface?data.surfaceLookaheadMs:data.lookaheadMs)/1000} с\n${poseRejected?'ПРИВЯЗКА ПОТЕРЯНА — линия скрыта':surface?(reasonNames[row.surfacePreview?.reason]??'Поверхность не проверена'):'Путь камеры в пространстве'}\n${check?'Проверка по той же записи: '+check.state:'Независимая локализация не проверена'}\nПрепятствия / дорога: не проверены`;
  }
  const mapPoint=event=>{const rect=map.getBoundingClientRect();return [(event.clientX-rect.left)*500/rect.width,(event.clientY-rect.top)*500/rect.height];};
  map.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();const p=mapPoint(event);drag={id:event.pointerId,at:p,start:p,pan:[...pan],moved:false};map.setPointerCapture(event.pointerId);});
  map.addEventListener('pointermove',event=>{if(!drag||event.pointerId!==drag.id)return;const p=mapPoint(event);drag.moved||=Math.hypot(p[0]-drag.start[0],p[1]-drag.start[1])>3;pan=[drag.pan[0]+p[0]-drag.start[0],drag.pan[1]+p[1]-drag.start[1]];render(lastSeconds);});
  map.addEventListener('pointerup',event=>{if(!drag||event.pointerId!==drag.id)return;const p=mapPoint(event),wasMoved=drag.moved;drag=null;if(wasMoved)return;let nearest=null,distance=20;for(const frame of data.frames){if(!frame.mapPoint)continue;const q=xy(frame.mapPoint),d=Math.hypot(q[0]-p[0],q[1]-p[1]);if(d<distance){nearest=frame;distance=d;}}if(nearest){video.pause();video.currentTime=nearest.seconds;render(nearest.seconds);}});
  map.addEventListener('pointercancel',()=>{drag=null;});
  map.addEventListener('wheel',event=>{event.preventDefault();const p=mapPoint(event),next=Math.max(.5,Math.min(12,zoom*Math.exp(-event.deltaY*.0015))),ratio=next/zoom;pan=[p[0]-250-(p[0]-250-pan[0])*ratio,p[1]-250-(p[1]-250-pan[1])*ratio];zoom=next;render(lastSeconds);},{passive:false});
  map.addEventListener('dblclick',()=>{zoom=1;pan=[0,0];render(lastSeconds);});
  if('requestVideoFrameCallback' in video){const next=(_now,meta)=>{render(meta.mediaTime);video.requestVideoFrameCallback(next);};video.requestVideoFrameCallback(next);}
  else video.addEventListener('timeupdate',()=>render(video.currentTime));
  [enabled,thickness,opacity,mode].forEach(el=>el.addEventListener('input',()=>render(video.currentTime)));
  video.addEventListener('seeked',()=>render(video.currentTime));render(0);
})().catch(()=>{document.getElementById('status').textContent='Не удалось прочитать проверенную временную шкалу. Линия не показывается.';});
