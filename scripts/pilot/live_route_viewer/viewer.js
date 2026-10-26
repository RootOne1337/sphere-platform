'use strict';
const byId=id=>document.getElementById(id);
const image=byId('image'),status=byId('status'),start=byId('start'),stop=byId('stop');
const confirmed=byId('confirmed'),hz=byId('hz'),tracker=byId('tracker'),trackerControl=byId('tracker-control');
let lastSequence=0,lastEpoch=null,lastSuccess=0,startUncertain=false,trackingAvailable=false;
start.addEventListener('click',async()=>{
  if(!confirmed.checked){status.textContent='Сначала подтвердите, что экран показывает игровой мир.';return;}
  startUncertain=true;start.disabled=true;
  const body={hz:Number(hz.value),sceneConfirmed:true};
  if(trackingAvailable)body.tracker=tracker.value;
  try{
    const r=await fetch('start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok)throw Error('start');
    hz.disabled=confirmed.disabled=tracker.disabled=true;stop.disabled=false;
  }catch{status.textContent='Запуск не подтверждён. Повтор автоматически не выполняется.';}
});
stop.addEventListener('click',async()=>{
  stop.disabled=true;image.removeAttribute('src');
  await fetch('stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});
});
async function poll(){
  try{
    const r=await fetch('sample',{cache:'no-store'});if(!r.ok)throw Error('sample');
    const data=await r.json(),sample=data.sample;
    trackingAvailable=Array.isArray(data.trackersAvailable)&&data.trackersAvailable.includes('anchored_flow');
    trackerControl.hidden=!trackingAvailable;
    start.disabled=data.oneShot||startUncertain;
    stop.disabled=!data.oneShot||['finished','failed'].includes(data.phase);
    if(sample&&sample.receiverAgeMs<=400){
      if(sample.epoch!==lastEpoch||sample.sequence!==lastSequence){
        image.src='data:image/jpeg;base64,'+sample.jpeg;
        lastSequence=sample.sequence;lastEpoch=sample.epoch;lastSuccess=performance.now();
      }
      const method=sample.method==='map_anchored_flow'?'сопровождение 3D-опор':sample.method==='not_attempted'?'расчёт не допущен':'поиск 3D-опор';
      status.textContent=`${data.phase} · ${sample.state}\nКадр ${sample.sequence} · ${sample.inliers} inliers · ${method}: ${sample.computeMs.toFixed(1)} мс\nВозраст от приёма ${sample.receiverAgeMs.toFixed(1)} мс · ${sample.reason}\nКоманд Android: 0`;
    }else{
      image.removeAttribute('src');
      status.textContent=`${data.phase}\nНет свежего кадра / привязки. Изображение скрыто.\nКоманд Android: 0`;
    }
  }catch{
    image.removeAttribute('src');status.textContent='Локальный наблюдатель недоступен. Старый кадр скрыт.';
  }finally{setTimeout(poll,200);}
}
setInterval(()=>{if(lastSuccess&&performance.now()-lastSuccess>600)image.removeAttribute('src');},200);
void poll();
