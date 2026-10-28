import {buildRouteMap,colorRoutePoints,exactRecordedFrame,nearestRouteCamera,readImportedRouteGeometry,routeCameraFrame,routeSourceMatches,routeTraceColor} from '@/src/features/stream/routeMapProjection';

test('projects camera positions and genuine points, leaving unobserved gaps disconnected',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:45000},
    {center:[2,1,0],ticks_90k:180000},{center:[3,1,1],ticks_90k:225000}];
  const points=[[0,0,1,255,255,255],[2,1,2,0,0,0]];
  const result=buildRouteMap(cameras,points)!;
  expect(result.cameras).toHaveLength(4);expect(result.points).toHaveLength(2);
  expect(result.segments).toHaveLength(2);expect(result.gaps).toBe(1);
  expect(result.cameras.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y))).toBe(true);
});
test('bounded point display and degenerate input remain explicit',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[2,0,0],ticks_90k:9000}];
  const result=buildRouteMap(cameras,Array.from({length:60000},(_,i)=>[i,1,0]))!;
  expect(result.points.length).toBeLessThanOrEqual(3000);
  expect(buildRouteMap([{center:[0,0,0],ticks_90k:0},{center:[0,0,0],ticks_90k:1}],[])).toBeNull();
  expect(buildRouteMap([{center:[NaN,0,0],ticks_90k:0},...cameras],[])).toBeNull();
});
test('timestamps moving backwards are never connected',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:9000},{center:[1,0,0],ticks_90k:8000}];
  expect(buildRouteMap(cameras,[])?.segments).toHaveLength(0);
  expect(buildRouteMap(cameras,[])?.gaps).toBe(1);
});

test('seek uses an exact recorded timestamp and binds to a matching source manifest',()=>{
  const rows=[0,3000,9000,18000].map(relative_ticks_90k=>({relative_ticks_90k}));
  expect(exactRecordedFrame(rows,9000)).toBe(2);
  for(const value of [-1,3001,NaN,Infinity,1.5])expect(exactRecordedFrame(rows,value)).toBeNull();
  expect(routeSourceMatches('a'.repeat(64),'a'.repeat(64))).toBe(true);
  expect(routeSourceMatches('a'.repeat(64),'b'.repeat(64))).toBe(false);
  expect(routeSourceMatches(null,null)).toBe(false);
  expect(routeSourceMatches('invalid','invalid')).toBe(false);
});
test('video position highlights only the nearest existing camera without interpolation',()=>{
  const cameras=[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000},{center:[2,0,0],ticks_90k:450000}];
  expect(nearestRouteCamera(cameras,320000)).toBe(2);
  expect(nearestRouteCamera(cameras,null)).toBeNull();
  expect(nearestRouteCamera([],0)).toBeNull();
});
test('imported geometry must be finite, bounded and match the original capture and its exact frames',()=>{
  const source='a'.repeat(64),ticks=new Set([0,90000]);
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  expect(readImportedRouteGeometry(scene,source,ticks).cameras).toHaveLength(2);
  expect(()=>readImportedRouteGeometry(scene,'b'.repeat(64),ticks)).toThrow(/другой записи/);
  expect(()=>readImportedRouteGeometry({...scene,cameras:[scene.cameras[0],{center:[1,0,0],ticks_90k:90001}]},source,ticks)).toThrow(/не совпадают/);
  expect(()=>readImportedRouteGeometry({...scene,cameras:[scene.cameras[1],scene.cameras[0]]},source,ticks)).toThrow(/не совпадают/);
  expect(()=>readImportedRouteGeometry({...scene,points:[[NaN,0,0,0,0,0]]},source,ticks)).toThrow(/Некорректные точки/);
});

const cameraAt=(center:number[],ticks_90k:number)=>({center,ticks_90k,camera_to_world:[[1,0,0,center[0]],[0,1,0,center[1]],[0,0,1,center[2]]]});
test('an actual forward then right turn stays forward then right instead of following arbitrary PCA signs',()=>{
  const cameras=[cameraAt([0,0,0],0),cameraAt([0,0,2],30000),cameraAt([2,0,2],60000)];
  const map=buildRouteMap(cameras,[])!;
  expect(map.orientation).toBe('camera');
  expect(map.cameras).toEqual([{x:0,y:0},{x:0,y:2},{x:2,y:2}]);
  expect(map.headings[0]).toEqual({x:0,y:1});
  // A proper 90-degree world rotation and translation cannot mirror the map.
  const transformed=cameras.map(c=>{const [x,y,z]=c.center;return {ticks_90k:c.ticks_90k,center:[z+7,y-3,-x+11],
    camera_to_world:[[0,0,1,z+7],[0,1,0,y-3],[-1,0,0,-x+11]]};});
  expect(buildRouteMap(transformed,[])?.cameras).toEqual(map.cameras);
});

test('import retains real rotations and rejects reflected, nonorthogonal or displaced optical frames',()=>{
  const source='a'.repeat(64),cameras=[cameraAt([0,0,0],0),cameraAt([0,0,1],30000)];
  const imported=readImportedRouteGeometry({schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,cameras,points:[]},source,new Set([0,30000]));
  expect(imported.cameras[0].camera_to_world).toEqual(cameras[0].camera_to_world);
  for(const pose of [[[-1,0,0,0],[0,1,0,0],[0,0,1,0]],[[1,.5,0,0],[0,1,0,0],[0,0,1,0]],[[1,0,0,8],[0,1,0,0],[0,0,1,0]]]){
    expect(routeCameraFrame({...cameras[0],camera_to_world:pose})).toBeNull();
    expect(()=>readImportedRouteGeometry({schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,cameras:[{...cameras[0],camera_to_world:pose},cameras[1]],points:[]},source,new Set([0,30000]))).toThrow(/ориентация/);
  }
  expect(buildRouteMap(cameras.map(({center,ticks_90k})=>({center,ticks_90k})),[])?.orientation).toBe('pca');
});

test('optical depth uses the selected camera and distinguishes points behind it from 3D range',()=>{
  const camera=cameraAt([0,0,0],0),points=[[3,0,4,255,0,0],[0,0,8,0,255,0],[0,0,-2,0,0,255]];
  const depth=colorRoutePoints(points,camera,'depth');
  expect(depth.available).toBe(true);expect(depth.behind).toBe(1);expect(depth.colors[2]).toBe('#334155');
  expect(depth.colors[0]).not.toBe(depth.colors[1]);expect(depth.colors).not.toContain(routeTraceColor);
  expect(colorRoutePoints(points,camera,'distance').low).toBeCloseTo(2.3);
  expect(colorRoutePoints(points,camera,'rgb').colors[0]).toBe('rgb(255,0,0)');
  expect(colorRoutePoints(points,{center:[0,0,0],ticks_90k:0},'depth').available).toBe(false);
  expect(colorRoutePoints([[0,0,-2,0,0,0]],camera,'depth').low).toBeNull();
});
