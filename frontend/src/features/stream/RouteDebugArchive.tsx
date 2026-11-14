'use client';
import {useEffect,useState} from 'react';
type Entry={id:string;at:number;bytes:number;folder:FileSystemDirectoryHandle;sha:string};
export function RouteDebugArchive({scope,clip,refresh}:{scope:string|null;clip:string|null;refresh:string}) {
  const [entries,setEntries]=useState<Entry[]>([]),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{
    let retired=false;setEntries([]);setNotice('');
    if(!scope||!clip||![scope,clip].every(v=>/^[0-9a-f]{32}$/.test(v)))return;
    void(async()=>{
      const root=await navigator.storage.getDirectory(),archive=await root.getDirectoryHandle('sphere-route-debug-'+scope),folder=await archive.getDirectoryHandle(clip);
      const iterable=folder as FileSystemDirectoryHandle&{values():AsyncIterableIterator<FileSystemHandle>};
      const found:Entry[]=[];let count=0;
      for await(const item of iterable.values()){
        if(++count>100)break;if(item.kind!=='directory'||!/^[0-9a-f]{32}$/.test(item.name))continue;
        try{const run=await folder.getDirectoryHandle(item.name),marker=await(await run.getFileHandle('COMPLETE')).getFile(),intent=await(await run.getFileHandle('intent.json')).getFile();
          if(marker.size>1024||intent.size>2048)continue;
          const receipt=JSON.parse(await marker.text()),meta=JSON.parse(await intent.text());
          if(!Number.isSafeInteger(receipt.bytes)||receipt.bytes<1||receipt.bytes>32*1024**2||!/^[0-9a-f]{64}$/.test(receipt.sha256)||meta.runId!==item.name||meta.clip!==clip||!Number.isFinite(meta.createdAt))continue;
          found.push({id:item.name,at:meta.createdAt,bytes:receipt.bytes,folder:run,sha:receipt.sha256});
        }catch{/* Incomplete runs remain on disk and are not offered as complete. */}
      }
      if(!retired){setEntries(found.sort((a,b)=>b.at-a.at).slice(0,8));setNotice(count>100?'Проверены первые 100 сеансов архива.':'');}
    })().catch(error=>{if(!retired)setNotice(error instanceof Error&&error.name==='NotFoundError'?'После первого завершённого теста здесь появятся отчёты.':'Архив сейчас недоступен; исходные записи сохранены.');});
    return()=>{retired=true;};
  },[scope,clip,refresh]);
  const download=async(item:Entry)=>{
    if(busy)return;setBusy(true);
    try{const file=await(await item.folder.getFileHandle('report.json')).getFile();if(file.size!==item.bytes)throw Error();
      const bytes=await file.arrayBuffer(),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
      if(sha!==item.sha)throw Error();const url=URL.createObjectURL(new Blob([bytes],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=`sphere-route-debug-${item.id.slice(0,8)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch{setNotice('Отчёт не прошёл проверку целостности. Сохранённые файлы не изменены.');}finally{setBusy(false);}
  };
  return <details className="rounded-lg border p-3 text-xs"><summary className="cursor-pointer font-medium">Локальный архив диагностики · {entries.length}</summary><p className="mt-2 text-muted-foreground">{notice||'Отчёты остаются в этом браузере после обновления страницы.'}</p><div className="mt-2 flex flex-wrap gap-2">{entries.map(item=><button type="button" key={item.id} disabled={busy} onClick={()=>{void download(item);}} className="rounded-md border px-3 py-2">{new Date(item.at).toLocaleString('ru-RU')} · {(item.bytes/1024).toFixed(0)} КБ · скачать</button>)}</div></details>;
}
