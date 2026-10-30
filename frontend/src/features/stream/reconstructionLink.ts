import type {ReconstructionJob} from './reconstructionClient';

const name='reconstruction-link.json';
const attemptPrefix='reconstruction-attempt-';
const idPattern=/^[0-9a-f]{32}$/;
const attemptPattern=/^reconstruction-attempt-([0-9a-f]{32})\.json$/;
const maxAttempts=200;

export function validReconstructionJob(value:unknown):value is ReconstructionJob {
  if(!value||typeof value!=='object')return false;
  const job=value as ReconstructionJob;
  return typeof job.id==='string'&&idPattern.test(job.id)&&typeof job.key==='string'&&/^[0-9a-f]{64}$/.test(job.key);
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
    if(previous&&previous.key!==job.key)throw Error('reconstruction_link_conflict');
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
    if(saved.key!==job.key)throw Error('reconstruction_link_conflict');
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
    if(same&&same.key!==job.key)throw Error('reconstruction_link_conflict');
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
