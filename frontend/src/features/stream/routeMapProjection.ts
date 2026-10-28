/** Diagnostic projection only: neither road surface nor metric trajectory. */
export type RouteMapCamera = {center:number[];ticks_90k:number};
export function routeSourceMatches(recorded:string|null|undefined,reconstructed:string|null|undefined):boolean {
  return typeof recorded==='string'&&/^[0-9a-f]{64}$/.test(recorded)&&recorded===reconstructed;
}
export type ImportedRouteGeometry={cameras:RouteMapCamera[];points:number[][]};
/** Strictly bind imported diagnostic geometry to the selected source index. */
export function readImportedRouteGeometry(value:unknown,sourceSha:string|null,ticks:ReadonlySet<number>):ImportedRouteGeometry {
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Некорректный файл геометрии.');
  const geometry=value as {schema?:unknown;source_manifest_sha256?:unknown;cameras?:unknown;points?:unknown};
  if(geometry.schema!=='sphere-recovered-scene-v1'||typeof geometry.source_manifest_sha256!=='string'||!routeSourceMatches(sourceSha,geometry.source_manifest_sha256))throw Error('Геометрия относится к другой записи или не содержит проверенную привязку.');
  if(!Array.isArray(geometry.cameras)||geometry.cameras.length<2||geometry.cameras.length>240||!Array.isArray(geometry.points)||geometry.points.length>60000)throw Error('Размер геометрии не поддерживается.');
  let last=-1;
  const cameras:RouteMapCamera[]=geometry.cameras.map((item:unknown)=>{
    if(!item||typeof item!=='object')throw Error('Некорректная камера.');
    const camera=item as {center?:unknown;ticks_90k?:unknown};
    if(!Array.isArray(camera.center)||camera.center.length!==3||camera.center.some(n=>typeof n!=='number'||!Number.isFinite(n))||typeof camera.ticks_90k!=='number'||!Number.isSafeInteger(camera.ticks_90k)||camera.ticks_90k<=last||!ticks.has(camera.ticks_90k))throw Error('Время или координаты камеры не совпадают с исходной записью.');
    last=camera.ticks_90k;return {center:[...camera.center],ticks_90k:camera.ticks_90k};
  });
  const points:number[][]=geometry.points.map((point:unknown)=>{
    if(!Array.isArray(point)||point.length!==6||point.some(n=>typeof n!=='number'||!Number.isFinite(n)))throw Error('Некорректные точки геометрии.');
    return [...point];
  });
  return {cameras,points};
}
/** Select a real reference only; no interpolation through unobserved intervals. */
export function nearestRouteCamera(cameras:RouteMapCamera[],ticks:number|null):number|null {
  if(ticks===null||!Number.isFinite(ticks)||!cameras.length)return null;
  let best=-1,distance=Infinity;
  cameras.forEach((camera,index)=>{const d=Math.abs(camera.ticks_90k-ticks);if(Number.isFinite(d)&&d<distance){best=index;distance=d;}});
  return best<0?null:best;
}
/** Camera timestamps originate in frames.jsonl and must match exactly. */
export function exactRecordedFrame(rows:{relative_ticks_90k:number}[],ticks:number):number|null {
  if(!Number.isSafeInteger(ticks)||ticks<0)return null;
  let lo=0,hi=rows.length;
  while(lo<hi){const mid=(lo+hi)>>>1;if(rows[mid].relative_ticks_90k<ticks)lo=mid+1;else hi=mid;}
  return lo<rows.length&&rows[lo].relative_ticks_90k===ticks?lo:null;
}
type XY={x:number;y:number};
export type RouteMap = {points:XY[];cameras:XY[];segments:{a:XY;b:XY}[];gaps:number};
type Vec=[number,number,number];
const dot=(a:Vec,b:Vec)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const norm=(a:Vec):Vec|null=>{const n=Math.hypot(...a);return n>1e-12?[a[0]/n,a[1]/n,a[2]/n]:null;};
const multiply=(m:number[][],v:Vec):Vec=>m.map(row=>row[0]*v[0]+row[1]*v[1]+row[2]*v[2]) as Vec;
function principal(m:number[][]):Vec|null {
  const columns=([0,1,2] as const).map(i=>[m[0][i],m[1][i],m[2][i]] as Vec);
  let v=norm(columns.sort((a,b)=>dot(b,b)-dot(a,a))[0]);if(!v)return null;
  for(let i=0;i<32;i++){const next=norm(multiply(m,v));if(!next)break;v=next;}
  return v;
}
export function buildRouteMap(cameras:RouteMapCamera[],points:number[][],maxPoints=3000):RouteMap|null {
  if(!Number.isInteger(maxPoints)||maxPoints<1||maxPoints>24000)return null;
  if(cameras.length<2||cameras.some(c=>c.center.length!==3||c.center.some(n=>!Number.isFinite(n))||!Number.isFinite(c.ticks_90k)))return null;
  const mean=[0,1,2].map(i=>cameras.reduce((sum,c)=>sum+c.center[i],0)/cameras.length) as Vec;
  const matrix=Array.from({length:3},()=>[0,0,0]);
  for(const camera of cameras){const d=camera.center.map((n,i)=>n-mean[i]);for(let i=0;i<3;i++)for(let j=0;j<3;j++)matrix[i][j]+=d[i]*d[j];}
  const u=principal(matrix);if(!u)return null;
  const eigen=dot(u,multiply(matrix,u));const remainder=matrix.map((row,i)=>row.map((n,j)=>n-eigen*u[i]*u[j]));
  let v=principal(remainder);
  // A straight camera trace has no second principal axis. Pick a stable
  // perpendicular for display, not an inferred ground plane.
  if(!v||Math.abs(dot(u,v))>.99){const axis:Vec=Math.abs(u[0])<.9?[1,0,0]:[0,1,0];const d=dot(axis,u);v=norm(axis.map((n,i)=>n-d*u[i]) as Vec);}
  if(!v)return null;
  const project=(p:number[]):XY=>{const d=p.slice(0,3).map((n,i)=>n-mean[i]) as Vec;return{x:dot(d,u),y:dot(d,v!)};};
  const cameras2=cameras.map(c=>project(c.center));
  const stride=Math.max(1,Math.ceil(points.length/maxPoints));
  const points2=points.filter((p,i)=>i%stride===0&&p.length>=3&&p.slice(0,3).every(Number.isFinite)).map(project);
  const segments:RouteMap['segments']=[];let gaps=0;
  for(let i=1;i<cameras.length;i++){const dt=(cameras[i].ticks_90k-cameras[i-1].ticks_90k)/90000;
    if(dt>0&&dt<=1)segments.push({a:cameras2[i-1],b:cameras2[i]});else gaps++;}
  return {points:points2,cameras:cameras2,segments,gaps};
}
