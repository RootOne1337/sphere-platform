import {assertReconstructionSource,routeRecordingIdentity} from '@/src/features/stream/routeSourceBinding';
import type {ReconstructionState} from '@/src/features/stream/reconstructionClient';

test('a known recording rejects foreign or absent manifest identity even when job reports ready',()=>{
  const sha='a'.repeat(64),ready={phase:'sparse_complete',source_manifest_sha256:sha,navigation:{phase:'ready'}} as ReconstructionState;
  expect(()=>assertReconstructionSource(ready,sha)).not.toThrow();
  for(const value of [undefined,null,'b'.repeat(64)])expect(()=>assertReconstructionSource({...ready,source_manifest_sha256:value},sha)).toThrow(/другой записи/);
  expect(()=>assertReconstructionSource({phase:'uploading'} as ReconstructionState,sha,true)).not.toThrow();
  expect(()=>assertReconstructionSource({phase:'uploading'} as ReconstructionState,sha)).toThrow();
});

test('visible identity names recording, capture and processing attempt separately',()=>{
  expect(routeRecordingIdentity('skuter1','36ae7f3f'.padEnd(32,'0'),'6a770406'.padEnd(32,'0'))).toBe('Запись: skuter1 · видео 36ae7f3f · обработка 6a770406');
});
