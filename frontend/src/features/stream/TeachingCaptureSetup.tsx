'use client';
import {useEffect,useRef,useState} from 'react';
import {Gauge,RefreshCw} from 'lucide-react';
import {api} from '@/lib/api';
import {Button} from '@/components/ui/button';
import {parseStreamQuality} from './streamQuality';
export type CaptureQuality={received_encoded_fps:number|null;received_bitrate_bps:number|null;max_media_gap_ms:number;
  gaps_over_200ms:number;gaps_over_500ms:number;disk_queue_high_water_bytes:number;max_disk_write_ms:number;
  cadence_30fps_confirmed:boolean;measured_seconds:number};
export function TeachingCaptureSetup({deviceId,disabled,quality}:{deviceId:string;disabled:boolean;quality:CaptureQuality|null}) {
  const [busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[notice,setNotice]=useState('Профиль применяется только к выбранному Android. Другие устройства сохраняют свои настройки.');
  const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[deviceId]);
  const apply=async(read=false)=>{
    if(disabled||request.current||!read&&uncertain)return;
    const controller=new AbortController();request.current=controller;setBusy(true);
    try{
      const path=`/streaming/${encodeURIComponent(deviceId)}/quality`;
      const {data}=read?await api.get(path,{signal:controller.signal,timeout:12000}):await api.post(path,
        {profile:'detail',max_fps:30,max_bitrate_bps:24_000_000},{signal:controller.signal,timeout:12000});
      if(controller.signal.aborted)return;
      const result=parseStreamQuality(data);if(!result?.supported)throw Error('quality_not_confirmed');
      if(!read&&(result.settings.profile!=='detail'||result.settings.max_fps!==30||result.settings.max_bitrate_bps!==24_000_000))throw Error('quality_mismatch');
      setUncertain(false);
      const a=result.active;
      setNotice(`Android подтвердил ${a?a.width+' × '+a.height+' · цель '+a.target_fps+' FPS · до '+(a.target_bitrate_bps/1e6).toFixed(1)+' Мбит/с':'настройки'}. Фактическую частоту и пропуски проверяем по записанному H.264.`);
    }catch{if(!controller.signal.aborted){setUncertain(true);setNotice('Подтверждение не получено. Настройки могли примениться. Сначала прочитайте состояние; повтор автоматически не отправляется.');}}
    finally{if(request.current===controller)request.current=null;if(!controller.signal.aborted)setBusy(false);}
  };
  return <section aria-label="Подготовка качественной съёмки" className="rounded-2xl border border-sky-500/20 bg-sky-500/5 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="flex items-center gap-2 text-sm font-semibold"><Gauge size={17}/>Master capture · исходное разрешение</h3><p className="mt-1 text-xs leading-5 text-muted-foreground">Полученный H.264 сохраняется без перекодирования и добавления кадров. Для съёмки: Full HD, рендер игры100%, стабильная камера.</p></div>
    <div className="flex gap-2"><Button size="sm" disabled={disabled||busy||uncertain} onClick={()=>{void apply();}}>Съёмка · 30 FPS / 24 Мбит</Button><Button size="sm" variant="outline" disabled={disabled||busy} onClick={()=>{void apply(true);}} aria-label="Проверить настройки съёмки"><RefreshCw size={14}/></Button></div></div>
    <p role="status" className="mt-2 text-xs leading-5 text-muted-foreground">{notice}</p>
    {quality&&<div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs tabular-nums"><strong className={quality.cadence_30fps_confirmed?'text-emerald-500':'text-amber-500'}>{quality.received_encoded_fps?.toFixed(1)??'—'} фактических FPS · {quality.cadence_30fps_confirmed?'частота подтверждена':'30 FPS пока не подтверждены'}</strong><span>{quality.received_bitrate_bps==null?'—':(quality.received_bitrate_bps/1e6).toFixed(2)} Мбит/с</span><span>Макс. интервал {quality.max_media_gap_ms.toFixed(1)} мс</span><span>Пропуски &gt;200 мс: {quality.gaps_over_200ms}</span><span>Пик очереди диска {(quality.disk_queue_high_water_bytes/1048576).toFixed(2)} МБ</span></div>}
  </section>;
}
