import type {ReconstructionJob} from './reconstructionClient';

const name='reconstruction-link.json';
const attemptPrefix='reconstruction-attempt-';
const idPattern=/^[0-9a-f]{32}$/;
const attemptPattern=/^reconstruction-attempt-([0-9a-f]{32})\.json$/;
const maxAttempts=200;
const sameCreation=(a:ReconstructionJob,b:ReconstructionJob)=>a.creation===undefined&&b.creation===undefined||!!a.creation&&!!b.creation&&a.creation.mask===b.creation.mask&&a.creation.steps===b.creation.steps&&a.creation.prepare_route===b.creation.prepare_route&&a.creation.route_only===b.creation.route_only;

export function validReconstructionJob(value:unknown):value is ReconstructionJob {
  if(!value||typeof value!=='object')return false;
  const job=value as ReconstructionJob;
  const c=job.creation;
  return typeof job.id==='string'&&idPattern.test(job.id)&&typeof job.key==='string'&&/^[0-9a-f]{64}$/.test(job.key)
    &&(c===undefined||!!c&&typeof c==='object'&&['none','avatar','game'].includes(c.mask)&&Number.isInteger(c.steps)&&c.steps>=1&&c.steps<=1000000&&c.prepare_route===true&&c.route_only===true);
}

async function readLink(folder:FileSystemDirectoryHandle,clip:string,fileName:string):Promise<ReconstructionJob|null> {
  let file:File;
  try{file=await(await folder.getFileHandle(fileName)).getFile();}
  catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')return null;throw error;}
  // A new OPFS file can remain empty if its first transactional write was interrupted.
  // The independently committed attempt records still allow recovery.
  if(file.size===0)return null;
  if(file.size>2048)throw Error('reconstruction_link_quota');
  const value=JSON.parse(await file.text());
  if(value.schema!=='sphere-local-reconstruction-link-v1'||value.clip!==clip||!validReconstructionJob(value.job))throw Error('reconstruction_link_binding');
  const attempt=attemptPattern.exec(fileName);
  if(attempt&&attempt[1]!==value.job.id)throw Error('reconstruction_link_binding');
  return value.job;
}

export async function readReconstructionLink(folder:FileSystemDirectoryHandle,clip:string):Promise<ReconstructionJob|null> {
  if(!idPattern.test(clip))throw Error('reconstruction_link_binding');
  return readLink(folder,clip,name);
}

/** A current link plus immutable per-attempt links; never expose capabilities in the UI. */
export async function listReconstructionLinks(folder:FileSystemDirectoryHandle,clip:string):Promise<ReconstructionJob[]> {
  if(!idPattern.test(clip))throw Error('reconstruction_link_binding');
  const current=await readReconstructionLink(folder,clip);
  const jobs=new Map<string,ReconstructionJob>();
  if(current)jobs.set(current.id,current);
  let count=0;
  const directory=folder as FileSystemDirectoryHandle&{entries?:()=>AsyncIterable<[string,FileSystemHandle]>};
  if(typeof directory.entries!=='function')throw Error('reconstruction_directory_listing_unavailable');
  for await(const [fileName] of directory.entries()) {
    if(!attemptPattern.test(fileName))continue;
    if(++count>maxAttempts)throw Error('reconstruction_attempt_quota');
    const job=await readLink(folder,clip,fileName);
    if(!job)continue;
    const previous=jobs.get(job.id);
    if(previous&&(previous.key!==job.key||!sameCreation(previous,job)))throw Error('reconstruction_link_conflict');
    jobs.set(job.id,job);
    if(jobs.size>maxAttempts)throw Error('reconstruction_attempt_quota');
  }
  return [...jobs.values()].sort((a,b)=>a.id.localeCompare(b.id));
}

async function writeLink(folder:FileSystemDirectoryHandle,clip:string,job:ReconstructionJob,fileName:string) {
  const output=await(await folder.getFileHandle(fileName,{create:true})).createWritable();
  try{await output.write(JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job}));await output.close();}
  catch(error){await output.abort().catch(()=>{});throw error;}
}

async function archiveLink(folder:FileSystemDirectoryHandle,clip:string,job:ReconstructionJob) {
  const fileName=`${attemptPrefix}${job.id}.json`;
  const saved=await readLink(folder,clip,fileName);
  if(saved) {
    if(saved.key!==job.key||!sameCreation(saved,job))throw Error('reconstruction_link_conflict');
    return;
  }
  await writeLink(folder,clip,job,fileName);
  const confirmed=await readLink(folder,clip,fileName);
  if(!confirmed||confirmed.id!==job.id||confirmed.key!==job.key)throw Error('reconstruction_link_not_confirmed');
}

/** Save all capabilities before switching the current link, including legacy v1 links. */
export async function saveReconstructionLink(folder:FileSystemDirectoryHandle,clip:string,job:ReconstructionJob) {
  if(!idPattern.test(clip)||!validReconstructionJob(job))throw Error('reconstruction_link_binding');
  const save=async()=>{
    const known=await listReconstructionLinks(folder,clip);
    const same=known.find(item=>item.id===job.id);
    if(same&&(same.key!==job.key||!sameCreation(same,job)))throw Error('reconstruction_link_conflict');
    if(!same&&known.length>=maxAttempts)throw Error('reconstruction_attempt_quota');
    const current=await readReconstructionLink(folder,clip);
    if(current)await archiveLink(folder,clip,current);
    await archiveLink(folder,clip,job);
    await writeLink(folder,clip,job,name);
  };
  // Web Locks protects parallel tabs. Without it, never replace an existing
  // current link: that would risk losing a concurrently created capability.
  if(typeof navigator!=='undefined'&&navigator.locks)await navigator.locks.request(`sphere-reconstruction-${clip}`,save);
  else {
    const current=await readReconstructionLink(folder,clip);
    if(current&&current.id!==job.id)throw Error('reconstruction_lock_unavailable');
    await save();
  }
}

/** Atomically bind one automatic intent to a recording; never replace an old attempt. */
export async function ensureAutomaticReconstructionLink(folder:FileSystemDirectoryHandle,clip:string,mask:'none'|'avatar'|'game',candidate?:ReconstructionJob):Promise<ReconstructionJob|null> {
  if(!idPattern.test(clip))throw Error('reconstruction_link_binding');
  if(candidate&&(!validReconstructionJob(candidate)||!candidate.creation||candidate.creation.mask!==mask))throw Error('reconstruction_link_binding');
  if(typeof navigator==='undefined'||!navigator.locks)throw Error('reconstruction_lock_unavailable');
  return navigator.locks.request(`sphere-reconstruction-${clip}`,async()=>{
    const current=await readReconstructionLink(folder,clip),known=await listReconstructionLinks(folder,clip);
    if(current)return current;
    if(known.length)return known.length===1&&known[0].creation?known[0]:null;
    const job:ReconstructionJob=candidate??{id:crypto.randomUUID().replaceAll('-',''),key:Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join(''),creation:{mask,steps:30000,prepare_route:true,route_only:true}};
    await archiveLink(folder,clip,job);await writeLink(folder,clip,job,name);
    return job;
  });
}

export async function automaticReconstructionStopped(folder:FileSystemDirectoryHandle,job:ReconstructionJob):Promise<boolean> {
  if(!validReconstructionJob(job))throw Error('reconstruction_link_binding');
  try {const f=await(await folder.getFileHandle(`reconstruction-auto-stopped-${job.id}.json`)).getFile();
    if(f.size>1024)throw Error('reconstruction_stop_invalid');
    const marker=JSON.parse(await f.text());if(marker.id!==job.id||marker.stopped!==true)throw Error('reconstruction_stop_invalid');return true;
  } catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')return false;throw error;}
}
export async function stopAutomaticReconstruction(folder:FileSystemDirectoryHandle,job:ReconstructionJob) {
  if(!validReconstructionJob(job))throw Error('reconstruction_link_binding');
  const writable=await(await folder.getFileHandle(`reconstruction-auto-stopped-${job.id}.json`,{create:true})).createWritable();
  try{await writable.write(JSON.stringify({id:job.id,stopped:true}));await writable.close();}catch(error){await writable.abort().catch(()=>{});throw error;}
}
