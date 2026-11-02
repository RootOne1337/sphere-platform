import {readImportedRouteGeometry,routeSourceMatches,type ImportedRouteGeometry} from './routeMapProjection';

/** A review choice, never a navigation or surface-model admission. */
export type SceneGeometrySelection={
  sourceKey:string;
  jobId:string;
  sourceManifestSha:string;
  id:string;
  label:string;
  diagnostic:boolean;
  geometry:ImportedRouteGeometry|null;
  recordingRange?:{firstTicks:number;lastTicks:number;frames:number};
};

export function readSceneRecordingRange(range:SceneGeometrySelection['recordingRange'],ticks:ReadonlySet<number>|undefined){
  if(!range)return null;
  if(!ticks?.size||ticks.size>36000||!Number.isSafeInteger(range.firstTicks)||!Number.isSafeInteger(range.lastTicks)
    ||range.firstTicks<0||range.lastTicks<range.firstTicks||range.frames!==ticks.size
    ||range.firstTicks!==Math.min(...ticks)||range.lastTicks!==Math.max(...ticks))throw Error('Интервал исходной записи не совпадает с подтверждённым индексом кадров.');
  return range;
}

export function readSceneGeometrySelection(selection:SceneGeometrySelection,context:{sourceKey?:string;jobId:string;sourceManifestSha:string|null;validTicks?:ReadonlySet<number>}):ImportedRouteGeometry|null {
  if(!context.sourceKey||selection.sourceKey!==context.sourceKey||selection.jobId!==context.jobId
    ||!routeSourceMatches(context.sourceManifestSha,selection.sourceManifestSha)
    ||typeof selection.id!=='string'||!selection.id||selection.id.length>256||typeof selection.label!=='string'||selection.label.length>256||typeof selection.diagnostic!=='boolean')throw Error('Выбранная схема не относится к текущей записи или заданию.');
  readSceneRecordingRange(selection.recordingRange,context.validTicks);
  if(!selection.geometry)return null;
  if(!context.validTicks?.size)throw Error('Индекс исходных кадров ещё не подтверждён.');
  return readImportedRouteGeometry({schema:'sphere-recovered-scene-v1',...selection.geometry},context.sourceManifestSha,context.validTicks);
}

export function sceneCameraCoverage(cameras:ImportedRouteGeometry['cameras'],range:SceneGeometrySelection['recordingRange'],ticks:ReadonlySet<number>|undefined){
  if(!cameras.length)return null;
  const source=readSceneRecordingRange(range,ticks),first=cameras[0].ticks_90k/90000,last=cameras.at(-1)!.ticks_90k/90000;
  let coveredSeconds=0,gapSeconds=0;
  for(let index=1;index<cameras.length;index++){
    const dt=(cameras[index].ticks_90k-cameras[index-1].ticks_90k)/90000;
    if(dt>0&&dt<=1)coveredSeconds+=dt;else if(dt>1)gapSeconds+=dt;
  }
  const sourceStart=source?source.firstTicks/90000:first,sourceEnd=source?source.lastTicks/90000:last;
  return {first,last,views:cameras.length,sourceStart,sourceEnd,knownSource:!!source,
    uncoveredStart:Math.max(0,first-sourceStart),uncoveredEnd:Math.max(0,sourceEnd-last),gapSeconds,coveredSeconds,
    fraction:sourceEnd>sourceStart?Math.min(1,coveredSeconds/(sourceEnd-sourceStart)):0};
}

/** Derived from measured centers only; no pose or timestamp interpolation. */
export function sceneCameraPath(geometry:ImportedRouteGeometry):number {
  return geometry.camera_path_units??geometry.cameras.reduce((sum,camera,index)=>index
    ?sum+Math.hypot(...camera.center.map((n,axis)=>n-geometry.cameras[index-1].center[axis])):sum,0);
}
