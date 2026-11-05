import {readLocalizationDiagnostic} from '@/src/features/stream/routeLocalizationDiagnostic';
const value={schema:'sphere-localization-observation-diagnostic-v1',candidateCount:3,maxRetainedLkCount:72,verifiedCandidateCount:1};
test('localization diagnostic projects only bounded same-reply stage counts',()=>{
  expect(readLocalizationDiagnostic({...value,descriptors:Array(100).fill('ignored'),candidateReferenceIndices:[1,3,7],flowRetainedByCandidate:[0,72,12],queryFeatures:350},true)).toEqual({...value,candidateReferenceIndices:[1,3,7],flowRetainedByCandidate:[0,72,12],queryFeatures:350});
  expect(readLocalizationDiagnostic({...value,flowRetainedByCandidate:[0,72,12],queryFeatures:350})).toEqual(value);
  expect(readLocalizationDiagnostic({...value,candidateCount:0,maxRetainedLkCount:0,verifiedCandidateCount:0})).toMatchObject({candidateCount:0,maxRetainedLkCount:0,verifiedCandidateCount:0});
  expect(readLocalizationDiagnostic({...value,candidateCount:null,maxRetainedLkCount:null,verifiedCandidateCount:null})).not.toBeNull();
  expect(readLocalizationDiagnostic({...value,flowRetainedByCandidate:[0,-1,0],queryFeatures:Infinity},true)).toEqual(value);
  expect(readLocalizationDiagnostic({...value,flowRetainedByCandidate:[0,0],queryFeatures:0},true)).toEqual({...value,queryFeatures:0});
});
test('missing, malformed or excessive optional telemetry is ignored',()=>{
  for(const input of [undefined,null,{}, {...value,schema:'unknown'},{...value,candidateCount:9},{...value,candidateCount:1.5},{...value,candidateCount:-1},
    {...value,maxRetainedLkCount:65537},{...value,maxRetainedLkCount:Infinity},{...value,verifiedCandidateCount:4}])expect(readLocalizationDiagnostic(input)).toBeNull();
});
