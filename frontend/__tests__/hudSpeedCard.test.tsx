import React from 'react';
import {render,screen} from '@testing-library/react';
import {HudSpeedCard} from '@/src/features/stream/TeachingReconstruction';
import {boundHudTelemetry,hudChart,type HudTelemetry} from '@/src/features/stream/reconstructionClient';
import {blackRussiaScooterProfile,defaultWalkingProfile,loadTeachingProfile} from '@/src/features/stream/teachingProfileStorage';
const hash='abc';
const telemetry:HudTelemetry={phase:'ready',source_manifest_sha256:hash,accepted_count:3,unknown_count:1,samples:[{ticks_90k:0,hud_kmh:10},{ticks_90k:9000,hud_kmh:20},{ticks_90k:18000,hud_kmh:null},{ticks_90k:27000,hud_kmh:30}]};
test('binds display to the current source hash',()=>{
  expect(boundHudTelemetry(telemetry,'different')).toBeUndefined();
  const {rerender}=render(<HudSpeedCard telemetry={telemetry} sourceManifestSha="different"/>);
  expect(screen.queryByText('Скорость на записи')).toBeNull();
  rerender(<HudSpeedCard telemetry={telemetry} sourceManifestSha={hash}/>);
  expect(screen.getByText('Скорость на записи')).toBeTruthy();
  expect(screen.getByText(/принятых: 3 · неизвестно: 1/)).toBeTruthy();
  expect(screen.getByText(/10–30 км\/ч/)).toBeTruthy();
});
test('breaks paths on unknown values and time gaps, preserving measured dots',()=>{
  const samples=[...telemetry.samples!,{ticks_90k:45001,hud_kmh:25},{ticks_90k:63001,hud_kmh:26}];
  const chart=hudChart(samples)!;
  expect(chart.segments.map(s=>s.length)).toEqual([2,1,2]);
  const {container}=render(<HudSpeedCard telemetry={{...telemetry,samples}} sourceManifestSha={hash}/>);
  expect(container.querySelectorAll('polyline')).toHaveLength(2);
  expect(container.querySelectorAll('circle')).toHaveLength(5);
});
test('rejects oversized and malformed charts',()=>{
  expect(hudChart(Array.from({length:602},(_,i)=>({ticks_90k:i,hud_kmh:1})))).toBeNull();
  expect(hudChart([{ticks_90k:1,hud_kmh:1},{ticks_90k:1,hud_kmh:2}])).toBeNull();
  expect(hudChart(Array.from({length:601},(_,i)=>({ticks_90k:i,hud_kmh:1})))?.segments[0]).toHaveLength(601);
});
test('decimated long recordings preserve observed continuity without joining actual source gaps',()=>{
  const samples=[0,90000,180000,270000,360000].map((ticks_90k,i)=>({ticks_90k,hud_kmh:20+i,gap_before:i===3}));
  expect(hudChart(samples)?.segments.map(s=>s.length)).toEqual([3,2]);
  expect(hudChart(samples.map((s,i)=>i===1?{...s,hud_kmh:null}:s))?.segments.map(s=>s.length)).toEqual([1,1,2]);
  expect(hudChart([{ticks_90k:0,hud_kmh:20,gap_before:false},{ticks_90k:90000,hud_kmh:21}])).toBeNull();
  expect(hudChart([{ticks_90k:0,hud_kmh:20,gap_before:'false' as unknown as boolean}])).toBeNull();
});
test('scooter preset persists a recognized HUD profile and invalid profiles fall back',()=>{
  const geometry={width:1920,height:1080},profile=blackRussiaScooterProfile(geometry);
  expect(profile.hudProfile).toBe('black_russia_scooter_v1');
  expect(defaultWalkingProfile(geometry).hudProfile).toBeUndefined();
  expect(loadTeachingProfile({getItem:()=>JSON.stringify(profile)},'x',geometry).hudProfile).toBe(profile.hudProfile);
  expect(loadTeachingProfile({getItem:()=>JSON.stringify({...profile,hudProfile:'other'})},'x',geometry).mode).toBe('stick');
});

