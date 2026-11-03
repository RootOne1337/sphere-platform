import {readImportedRouteGeometry} from '@/src/features/stream/routeMapProjection';
import {readSceneGeometrySelection,readSceneRecordingRange,sceneCameraCoverage,type SceneGeometrySelection} from '@/src/features/stream/sceneGeometrySelection';

const sha='a'.repeat(64),ticks=new Set([0,90000,180000]);
const raw={schema:'sphere-recovered-scene-v1',source_manifest_sha256:sha,camera_path_units:2,
  cameras:[0,90000,180000].map((ticks_90k,i)=>({ticks_90k,center:[i,0,0],image:`${String(i).padStart(8,'0')}.png`,camera_to_world:[[1,0,0,i],[0,1,0,0],[0,0,1,0]],intrinsics:{width:1920,height:1080,fx:604,fy:604,cx:960,cy:540}})),points:[[1,1,2,255,0,0]]};
const selection=():SceneGeometrySelection=>({sourceKey:'account:clip',jobId:'job',sourceManifestSha:sha,id:'diagnostic',label:'Выбранные камеры',diagnostic:true,geometry:readImportedRouteGeometry(raw,sha,ticks),recordingRange:{firstTicks:0,lastTicks:180000,frames:3}});
const context={sourceKey:'account:clip',jobId:'job',sourceManifestSha:sha,validTicks:ticks};

test('selected3D geometry retains the exact bound camera pose, image, intrinsics and points without mutating shared2D arrays',()=>{
  const selected=selection(),result=readSceneGeometrySelection(selected,context)!;
  expect(result.source_manifest_sha256).toBe(sha);expect(result.camera_path_units).toBe(2);
  expect(result.cameras).toEqual(raw.cameras);expect(result.points).toEqual(raw.points);
  expect(result.cameras).not.toBe(selected.geometry!.cameras);
  result.cameras[0].center[0]=100;expect(selected.geometry!.cameras[0].center[0]).toBe(0);
});
test('wrong account, job, capture, or exact source ticks fail closed, including a loading selection',()=>{
  for(const changed of [{sourceKey:'other:clip'},{jobId:'other'},{sourceManifestSha:'b'.repeat(64)},{validTicks:new Set([0,90001,180000])}]){
    expect(()=>readSceneGeometrySelection(selection(),{...context,...changed})).toThrow();
  }
  expect(readSceneGeometrySelection({...selection(),geometry:null},context)).toBeNull();
  expect(()=>readSceneGeometrySelection({...selection(),sourceKey:'other',geometry:null},context)).toThrow();
});
test('image traversal, bad calibration and nonfinite path cannot enter3D from imported geometry',()=>{
  for(const camera of [{...raw.cameras[0],image:'../00000000.png'},{...raw.cameras[0],intrinsics:{...raw.cameras[0].intrinsics,fx:0}},{...raw.cameras[0],intrinsics:{...raw.cameras[0].intrinsics,cx:NaN}}]){
    expect(()=>readImportedRouteGeometry({...raw,cameras:[camera,...raw.cameras.slice(1)]},sha,ticks)).toThrow();
  }
  expect(()=>readImportedRouteGeometry({...raw,camera_path_units:Infinity},sha,ticks)).toThrow();
});
test('coverage uses the verified full source range, not the reconstructed subset as its denominator',()=>{
  const sourceTicks=new Set([0,513000,900000,1800000,3276000,3321000]);
  const cameras=[513000,900000,1800000,3276000].map((ticks_90k,i)=>({ticks_90k,center:[i,0,0]}));
  const range={firstTicks:0,lastTicks:3321000,frames:sourceTicks.size};
  const view=sceneCameraCoverage(cameras,range,sourceTicks)!;
  expect(view.sourceEnd).toBe(36.9);expect(view.uncoveredStart).toBe(5.7);expect(view.uncoveredEnd).toBeCloseTo(.5);
  expect(view.knownSource).toBe(true);expect(view.fraction).toBeLessThan(1);expect(view.gapSeconds).toBeGreaterThan(0);
  expect(view.sourceFrames).toBe(sourceTicks.size);
  expect(view.cameraIntervals).toEqual([{first:5.7,last:5.7},{first:10,last:10},{first:20,last:20},{first:36.4,last:36.4}]);
  expect(view.gaps).toEqual([{first:5.7,last:10},{first:10,last:20},{first:20,last:36.4}]);
  const legacy=sceneCameraCoverage(cameras,undefined,sourceTicks)!;
  expect(legacy.knownSource).toBe(false);
  expect(()=>readSceneRecordingRange({...range,firstTicks:513000},sourceTicks)).toThrow();
  expect(()=>readSceneRecordingRange({...range,frames:99},sourceTicks)).toThrow();
});
test('the valid36000-frame source index remains supported by3D coverage',()=>{
  const sourceTicks=new Set(Array.from({length:36000},(_,i)=>i*1500));
  expect(readSceneRecordingRange({firstTicks:0,lastTicks:35999*1500,frames:36000},sourceTicks)?.frames).toBe(36000);
});
