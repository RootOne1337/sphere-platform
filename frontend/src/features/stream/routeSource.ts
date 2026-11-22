/** Shared verified OPFS source; no raw frames, credentials or native input owner. */
export type RecordedRouteRow={index:number;offset:number;bytes:number;relative_ticks_90k:number;key:boolean;seekable?:boolean;sha256:string;worker_observed_at_ms:number};
export type RouteSource={clip:string;scope:string;manifestSha:string;rows:RecordedRouteRow[];folder:FileSystemDirectoryHandle};

export async function readRecordedRouteFrame(source:RouteSource,index:number,canvas:HTMLCanvasElement,signal:AbortSignal) {
  if(!Number.isSafeInteger(index)||index<0||index>=source.rows.length)throw Error('Индекс опорного кадра недоступен.');
  const check=()=>{if(signal.aborted)throw Error('frame_cancelled');};
  const digest=async(data:ArrayBuffer)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
  if(typeof VideoDecoder==='undefined')throw Error('Для опорного кадра нужен WebCodecs.');
  const file=await(await source.folder.getFileHandle('video.h264')).getFile();check();
  let first=index;while(first>0&&!(source.rows[first].seekable??source.rows[first].key))first--;
  if(!source.rows[first].key||index-first>240)throw Error('Слишком длинная цепочка до ключевого кадра.');
  const row=source.rows[first],initial=await file.slice(row.offset,row.offset+row.bytes).arrayBuffer();check();
  const data=new Uint8Array(initial);let codec:string|null=null;
  for(let i=0;i+7<data.length;i++)if(data[i]===0&&data[i+1]===0){const at=data[i+2]===1?i+3:data[i+2]===0&&data[i+3]===1?i+4:-1;
    if(at>=0&&(data[at]&31)===7){codec='avc1.'+Array.from(data.slice(at+1,at+4),v=>v.toString(16).padStart(2,'0')).join('');break;}}
  if(!codec)throw Error('SPS опорного кадра не найден.');
  if(!(await VideoDecoder.isConfigSupported({codec})).supported)throw Error('Профиль опорного кадра не поддерживается.');check();
  let failed=false,drawn=false;
  const decoder=new VideoDecoder({output:frame=>{try{if(!signal.aborted&&frame.timestamp===Math.round(source.rows[index].relative_ticks_90k*1000000/90000)){
    if(frame.displayWidth*frame.displayHeight>8*1024**2){failed=true;return;}
    canvas.width=frame.displayWidth;canvas.height=frame.displayHeight;canvas.getContext('2d')?.drawImage(frame,0,0);drawn=true;
  }}finally{frame.close();}},error:()=>{failed=true;}});
  const close=()=>{if(decoder.state!=='closed')decoder.close();};signal.addEventListener('abort',close,{once:true});
  try{
    decoder.configure({codec});
    for(let i=first;i<=index;i++){
      check();const r=source.rows[i];
      if(!Number.isSafeInteger(r.bytes)||r.bytes<1||r.bytes>2*1024**2)throw Error('Размер опорного кадра превышен.');
      const raw=i===first?initial:await file.slice(r.offset,r.offset+r.bytes).arrayBuffer();check();
      if(raw.byteLength!==r.bytes||await digest(raw)!==r.sha256)throw Error('Контрольная сумма опорного кадра не совпала.');check();
      decoder.decode(new EncodedVideoChunk({type:r.key?'key':'delta',timestamp:Math.round(r.relative_ticks_90k*1000000/90000),data:raw}));
      if(decoder.decodeQueueSize>8)await new Promise<void>((resolve,reject)=>{
        const onAbort=()=>finish(Error('frame_cancelled')),onProgress=()=>finish();
        const timeout=setTimeout(()=>finish(Error('Декодер опорного кадра не ответил.')),2000);
        const finish=(error?:Error)=>{clearTimeout(timeout);signal.removeEventListener('abort',onAbort);decoder.removeEventListener('dequeue',onProgress);error?reject(error):resolve();};
        signal.addEventListener('abort',onAbort,{once:true});decoder.addEventListener('dequeue',onProgress,{once:true});
      });
    }
    await decoder.flush();check();if(failed||!drawn)throw Error('Декодирование опорного кадра не подтверждено.');
  }finally{signal.removeEventListener('abort',close);close();}
}
