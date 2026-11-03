import {navigationExpectedSource,navigationPreparationSource,navigationReadyForGeometry} from '@/src/features/stream/navigationGeometrySource';
import type {NavigationGeometrySelection} from '@/src/features/stream/navigationGeometrySource';
import type {NavigationState} from '@/src/features/stream/reconstructionClient';

const selected:NavigationGeometrySelection={alternativeId:'retained-173',geometry_sha256:'a'.repeat(64),cameras:173,points:20556,label:'Сохранённая схема'};
const source={alternativeId:'retained-173',geometry_sha256:selected.geometry_sha256,cameras:173,points:20556,runtime_family:'reference_lk' as const};
test('counts and a valid view alone cannot authorize preparation or movement',()=>{
  expect(navigationPreparationSource({phase:'not_prepared'},selected)).toBeNull();
  expect(navigationReadyForGeometry({phase:'not_prepared',preparationSources:[source]},selected,true)).toBe(false);
  expect(navigationReadyForGeometry({phase:'ready'},selected,true)).toBe(false);
});
test('only one exact backend-qualified source is offered for preparing the selected geometry',()=>{
  expect(navigationPreparationSource({phase:'not_prepared',preparationSources:[source]},selected)).toEqual(source);
  expect(navigationPreparationSource({phase:'not_prepared',preparationSources:[source,source]},selected)).toBeNull();
  for(const changed of [{geometry_sha256:'b'.repeat(64)},{alternativeId:'other'},{cameras:172},{points:20555},{runtime_family:'unknown'}]){
    expect(navigationPreparationSource({phase:'not_prepared',preparationSources:[{...source,...changed}]} as NavigationState,selected)).toBeNull();
  }
});
test('an alternative ready map must match both the selected ID and geometry bytes',()=>{
  const assets:NavigationState={phase:'ready',source};
  expect(navigationReadyForGeometry(assets,selected,true)).toBe(true);
  expect(navigationReadyForGeometry(assets,{...selected,alternativeId:'other'},true)).toBe(false);
  expect(navigationReadyForGeometry(assets,{...selected,geometry_sha256:'b'.repeat(64)},true)).toBe(false);
  expect(navigationReadyForGeometry(assets,null,false)).toBe(false);
  expect(navigationReadyForGeometry({...assets,phase:'features'},selected,true)).toBe(false);
});
test('legacy ready primary maps remain compatible without promoting an inspected alternative',()=>{
  const primary={...selected,alternativeId:null};
  expect(navigationReadyForGeometry({phase:'ready'},null,false)).toBe(true);
  expect(navigationReadyForGeometry({phase:'ready'},null,true)).toBe(false);
  expect(navigationReadyForGeometry({phase:'ready'},primary,true)).toBe(true);
  expect(navigationReadyForGeometry({phase:'ready'},selected,true)).toBe(false);
});
test('a start fence contains only the exact validated public binding and legacy requests stay unchanged',()=>{
  expect(navigationExpectedSource({phase:'ready',source},selected,true)).toEqual({alternativeId:source.alternativeId,geometry_sha256:source.geometry_sha256,runtime_family:'reference_lk'});
  expect(navigationExpectedSource({phase:'ready',source},selected,true)).not.toHaveProperty('cameras');
  expect(navigationExpectedSource({phase:'ready',source}, {...selected,alternativeId:'other'},true)).toBeUndefined();
  expect(navigationExpectedSource({phase:'ready'},null,false)).toBeUndefined();
  for(const changed of [{alternativeId:'../native'},{runtime_family:'unknown'},{geometry_sha256:'invalid'}]){
    const value={...source,...changed};
    expect(navigationReadyForGeometry({phase:'ready',source:value} as NavigationState,{...selected,alternativeId:value.alternativeId,geometry_sha256:value.geometry_sha256},true)).toBe(false);
    expect(navigationExpectedSource({phase:'ready',source:value} as NavigationState,selected,true)).toBeUndefined();
  }
});
