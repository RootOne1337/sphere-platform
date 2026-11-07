/** Human labels are sidecars: sealed media, journal and COMPLETE never change. */
const idPattern = /^[0-9a-f]{32}$/;
const hashPattern = /^[0-9a-f]{64}$/;
const validTitle = (value: unknown): value is string => typeof value === 'string'
  && value.trim() === value && value.length > 0 && value.length <= 128 && !/[\u0000-\u001f\u007f]/.test(value);

export function teachingTitle(draft: string, id: string, at: number): string {
  if (!idPattern.test(id) || !Number.isFinite(at) || !Number.isFinite(new Date(at).getTime())) throw Error('invalid_recording_identity');
  const custom = draft.trim();
  if (custom && custom.toLocaleLowerCase('ru-RU') !== 'маршрут') {
    if (!validTitle(custom)) throw Error('invalid_recording_title');
    return custom;
  }
  const date = new Date(at), pad = (n: number) => String(n).padStart(2, '0');
  return `Маршрут ${pad(date.getDate())}.${pad(date.getMonth()+1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())} · ${id.slice(0,8)}`;
}

export function teachingDate(at: number): string {
  return Number.isFinite(at) && at > 0 && Number.isFinite(new Date(at).getTime())
    ? new Date(at).toLocaleString('ru-RU') : 'Время не сохранено';
}

export function seekTeachingSecond(rows:ReadonlyArray<{relative_ticks_90k:number}>,position:number,delta:number):number {
  if(!rows.length)return 0;
  const at=Math.max(0,Math.min(rows.length-1,position)),target=rows[at].relative_ticks_90k+delta*90000;
  let low=0,high=rows.length;
  while(low<high){const mid=(low+high)>>>1;if(rows[mid].relative_ticks_90k<target)low=mid+1;else high=mid;}
  const next=delta<0&&low<rows.length&&rows[low].relative_ticks_90k>target?low-1:low;
  return Math.max(0,Math.min(rows.length-1,next));
}

async function digest(bytes: ArrayBuffer): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)), v=>v.toString(16).padStart(2,'0')).join('');
}

export function parseTeachingLabel(raw: string, id: string, manifestSha: string): string | null {
  if (raw.length > 2048 || !idPattern.test(id) || !hashPattern.test(manifestSha)) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).sort().join(',') !== 'id,manifest_sha256,schema,title,updated_at_ms'
      || value.schema !== 'sphere-teaching-label-v1' || value.id !== id || value.manifest_sha256 !== manifestSha
      || !validTitle(value.title) || !Number.isSafeInteger(value.updated_at_ms) || value.updated_at_ms < 0) return null;
    return value.title;
  } catch { return null; }
}

export async function readTeachingLabel(folder: FileSystemDirectoryHandle, id: string, manifest: ArrayBuffer): Promise<string | null> {
  try {
    const file = await (await folder.getFileHandle('label.json')).getFile();
    if (file.size > 2048) return null;
    return parseTeachingLabel(await file.text(),id,await digest(manifest));
  } catch { return null; }
}

export async function renameTeachingLabel(folder: FileSystemDirectoryHandle, id: string, title: string): Promise<void> {
  const clean = title.trim();
  if (!idPattern.test(id) || !validTitle(clean)) throw Error('Введите название от 1 до 128 символов.');
  const manifest = await (await folder.getFileHandle('manifest.json')).getFile();
  if (manifest.size > 65536) throw Error('Размер описания записи некорректен.');
  const bytes = await manifest.arrayBuffer(), data = JSON.parse(new TextDecoder().decode(bytes));
  if (data.id !== id || !['sphere-browser-teaching-v1','sphere-browser-teaching-v2'].includes(data.schema)) throw Error('Выбранная запись изменилась.');
  const label = {schema:'sphere-teaching-label-v1',id,manifest_sha256:await digest(bytes),title:clean,updated_at_ms:Date.now()};
  const stream = await (await folder.getFileHandle('label.json',{create:true})).createWritable();
  try { await stream.write(JSON.stringify(label)+'\n'); await stream.close(); }
  catch (error) { try { await stream.abort(); } catch { /* Preserve the original write error. */ } throw error; }
}
