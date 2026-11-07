'use client';
import {useEffect,useState} from 'react';
import {reconstructionRequest,type ReconstructionJob} from './reconstructionClient';

export default function RecordedSourceFrame({job,image}:{job:ReconstructionJob;image:string}) {
  const [url,setUrl]=useState<string|null>(null),[error,setError]=useState(false);
  useEffect(()=>{
    let retired=false,objectUrl:string|null=null;const abort=new AbortController();setUrl(null);setError(false);
    void(async()=>{
      if(!/^[0-9]{8}\.png$/.test(image))throw Error('invalid_frame');
      const response=await reconstructionRequest(`/jobs/${job.id}/frame/${image}`,job,{signal:abort.signal});
      const body=await response.blob();if(retired)return;
      if(body.size>2*1048576||body.type!=='image/jpeg')throw Error('preview_quota');
      objectUrl=URL.createObjectURL(body);setUrl(objectUrl);
    })().catch(()=>{if(!retired)setError(true);});
    return()=>{retired=true;abort.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);};
  },[job,image]);
  return <div className="p-3">{url?<img src={url} alt={`Исходный кадр ${image}`} className="mx-auto max-h-72 max-w-full rounded-lg"/>:<p className="text-xs text-muted-foreground">{error?'Исходный кадр не подтверждён.':'Загружаем исходный ракурс…'}</p>}</div>;
}
