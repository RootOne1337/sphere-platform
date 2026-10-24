import type {ReconstructionJob} from './reconstructionClient';
const name='reconstruction-link.json';
export function validReconstructionJob(value:unknown):value is ReconstructionJob {
  if(!value||typeof value!=='object')return false;
  const job=value as ReconstructionJob;
  return typeof job.id==='string'&&/^[0-9a-f]{32}$/.test(job.id)&&typeof job.key==='string'&&/^[0-9a-f]{64}$/.test(job.key);
}
export async function readReconstructionLink(folder:FileSystemDirectoryHandle,clip:string):Promise<ReconstructionJob|null> {
  let file:File;
  try{file=await(await folder.getFileHandle(name)).getFile();}catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')return null;throw error;}
  if(file.size>2048)throw Error('reconstruction_link_quota');
  const value=JSON.parse(await file.text());
  if(value.schema!=='sphere-local-reconstruction-link-v1'||value.clip!==clip||!validReconstructionJob(value.job))throw Error('reconstruction_link_binding');
  return value.job;
}
export async function saveReconstructionLink(folder:FileSystemDirectoryHandle,clip:string,job:ReconstructionJob) {
  if(!/^[0-9a-f]{32}$/.test(clip)||!validReconstructionJob(job))throw Error('reconstruction_link_binding');
  const output=await(await folder.getFileHandle(name,{create:true})).createWritable();
  try{await output.write(JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job}));await output.close();}
  catch(error){await output.abort().catch(()=>{});throw error;}
}
