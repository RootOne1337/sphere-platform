import type {NavigationMapSource,NavigationPreparationSource,NavigationState} from './reconstructionClient';

/** A source-validated view is not by itself a prepared navigation map. */
export type NavigationGeometrySelection={alternativeId:string|null;geometry_sha256:string;label:string;cameras:number;points:number};
const alternative=/^[a-z0-9][a-z0-9-]{0,47}$/;
const sha=/^[0-9a-f]{64}$/;
export function navigationPreparationSource(assets:NavigationState|null,selection:NavigationGeometrySelection|null):NavigationPreparationSource|null {
  if(!selection?.alternativeId||!alternative.test(selection.alternativeId)||!sha.test(selection.geometry_sha256))return null;
  const candidates=assets?.preparationSources;
  if(!Array.isArray(candidates)||candidates.length>16)return null;
  const matches=candidates.filter(item=>item&&item.alternativeId===selection.alternativeId&&item.geometry_sha256===selection.geometry_sha256
    &&item.runtime_family==='reference_lk'&&Number.isInteger(item.cameras)&&item.cameras>=2&&item.cameras<=240&&item.cameras===selection.cameras
    &&Number.isInteger(item.points)&&item.points>=0&&item.points<=60000&&item.points===selection.points);
  return matches.length===1?matches[0]:null;
}

/** A ready legacy primary map remains compatible; alternatives require an exact source binding. */
export function navigationReadyForGeometry(assets:NavigationState|null,selection:NavigationGeometrySelection|null,hasSourceView:boolean):boolean {
  if(assets?.phase!=='ready')return false;
  if(assets.source){
    const source=assets.source;
    return !!selection&&(source.alternativeId===null||typeof source.alternativeId==='string'&&alternative.test(source.alternativeId))
      &&sha.test(source.geometry_sha256)&&source.geometry_sha256===selection.geometry_sha256
      &&source.alternativeId===selection.alternativeId&&['legacy_sparse','reference_lk'].includes(source.runtime_family);
  }
  return !hasSourceView||selection?.alternativeId===null;
}

/** Hidden-HUD recordings require both backend support and the selected ready map. */
export function visualTempoAvailable(recordedWithoutHud:boolean,assets:NavigationState|null,selection:NavigationGeometrySelection|null,hasSourceView:boolean):boolean {
  return recordedWithoutHud&&assets?.vehicleVisualTempoAvailable===true&&!!assets.source&&navigationReadyForGeometry(assets,selection,hasSourceView);
}

/** Freeze only the validated public binding, never catalog metadata or arbitrary status fields. */
export function navigationExpectedSource(assets:NavigationState|null,selection:NavigationGeometrySelection|null,hasSourceView:boolean):NavigationMapSource|undefined {
  if(!navigationReadyForGeometry(assets,selection,hasSourceView)||!assets?.source)return undefined;
  const {alternativeId,geometry_sha256,runtime_family}=assets.source;
  return {alternativeId,geometry_sha256,runtime_family};
}

export const navigationGeometryIdentity=(source:NavigationGeometrySelection|null)=>source?JSON.stringify([source.alternativeId,source.geometry_sha256]):null;
