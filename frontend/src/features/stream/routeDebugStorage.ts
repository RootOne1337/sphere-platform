/** Append-only completed reports in OPFS, separate from original recordings. */
export type DebugSave={state:'saved'|'existing'|'unconfirmed';runId:string};
const id=/^[0-9a-f]{32}$/,pending=new Map<string,Promise<DebugSave>>();
export function saveRouteDebugReport(scope:string,clip:string,runId:string,report:unknown):Promise<DebugSave> {
  if(![scope,clip,runId].every(v=>id.test(v)))return Promise.reject(Error('debug_identity_invalid'));
  const key=`${scope}/${clip}/${runId}`,existing=pending.get(key);if(existing)return existing;
  const task=(async():Promise<DebugSave>=>{
    const bytes=new TextEncoder().encode(JSON.stringify(report));
    if(bytes.byteLength>32*1024**2)throw Error('debug_report_quota');
    const estimate=await navigator.storage.estimate();
    if((estimate.quota??0)-(estimate.usage??0)<bytes.byteLength+4*1024**2)throw Error('debug_storage_quota');
    const root=await navigator.storage.getDirectory(),archive=await root.getDirectoryHandle('sphere-route-debug-'+scope,{create:true});
    const passage=await archive.getDirectoryHandle(clip,{create:true});
    const hash=async(data:ArrayBuffer)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
    const digest=await hash(Uint8Array.from(bytes).buffer);
    let old:FileSystemDirectoryHandle|null=null;
    try{old=await passage.getDirectoryHandle(runId);}catch(error){if(!(error instanceof Error)||error.name!=='NotFoundError')throw error;}
    if(old){
      try{const marker=await(await old.getFileHandle('COMPLETE')).getFile();if(marker.size>1024)throw Error();
        const receipt=JSON.parse(await marker.text()),file=await(await old.getFileHandle('report.json')).getFile();
        if(receipt.bytes===bytes.length&&file.size===bytes.length&&receipt.sha256===digest&&await hash(await file.arrayBuffer())===digest)return {state:'existing',runId};
      }catch{/* An incomplete or changed report is preserved, never overwritten. */}
      return {state:'unconfirmed',runId};
    }
    const folder=await passage.getDirectoryHandle(runId,{create:true});
    const write=async(name:string,data:Uint8Array)=>{
      const file=await folder.getFileHandle(name,{create:true}),writer=await file.createWritable();
      try{await writer.write(Uint8Array.from(data).buffer);await writer.close();}catch(error){try{await writer.abort();}catch{/* Never repeat an uncertain close. */}throw error;}
    };
    await write('intent.json',new TextEncoder().encode(JSON.stringify({schema:'sphere-route-debug-intent-v1',runId,clip,createdAt:Date.now(),bytes:bytes.length,sha256:digest})));
    await write('report.json',bytes);
    await write('COMPLETE',new TextEncoder().encode(JSON.stringify({sha256:digest,bytes:bytes.length})));
    return {state:'saved',runId};
  })();
  pending.set(key,task);void task.finally(()=>pending.delete(key)).catch(()=>{});return task;
}
