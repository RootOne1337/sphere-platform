import {cameraMotionRequiresReview,prepareRoute,preparationError,preparationQuotaReached,routeCoverageLabel} from '@/src/features/stream/routePreparation';
import {reconstructionRequest,ReconstructionResponseError} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));

const job={id:'a'.repeat(32),key:'b'.repeat(64)},scope='c'.repeat(32),clip='d'.repeat(32);
beforeEach(()=>{sessionStorage.clear();jest.clearAllMocks();Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});});

test('unknown preparation outcome is reconciled with the same intent',async()=>{
  jest.mocked(reconstructionRequest).mockRejectedValueOnce(Error('network_result_unknown'))
    .mockResolvedValueOnce({json:async()=>({phase:'ready'})} as Response);
  await expect(prepareRoute(job,scope,clip)).rejects.toThrow('network_result_unknown');
  await expect(prepareRoute(job,scope,clip)).resolves.toEqual({phase:'ready'});
  const calls=jest.mocked(reconstructionRequest).mock.calls;
  expect(calls).toHaveLength(2);
  expect(JSON.parse(String(calls[0][2]?.body))).toEqual(JSON.parse(String(calls[1][2]?.body)));
  expect(sessionStorage.length).toBe(0);
});

test('a confirmed memory refusal is not presented as an unknown execution',()=>{
  expect(preparationError(new ReconstructionResponseError(409,'resource_guard'))).toMatch(/Не хватает ресурсов/);
  expect(preparationError(Error('network_result_unknown'))).toMatch(/Ответ не подтверждён/);
});

test('partial source coverage displays measured ranges without claiming interpolated cameras',()=>{
  expect(routeCoverageLabel({cameras:54,landmarks:1236,camera_trace_only:true,last_seconds:28.258,
    source_coverage:{recording_start_seconds:0,recording_end_seconds:33.258,uncovered_start_seconds:0,uncovered_end_seconds:5,endpoints_observed:false},
    map_support:{all_reference_neighborhoods_supported:true,unobserved_intervals:[{start_seconds:10.807,end_seconds:12.341}]}}))
    .toBe('54 восстановленных ракурсов · карта до 28.26 с из 33.26 с записи · разрывы: 10.81–12.34 с');
  expect(routeCoverageLabel(undefined)).toBeNull();
});
test('only the worker confirmed quota rejection blocks another attempt',()=>{
  expect(preparationQuotaReached(new ReconstructionResponseError(409,'route_preparation_attempt_quota'))).toBe(true);
  expect(preparationQuotaReached(new ReconstructionResponseError(500,'route_preparation_attempt_quota'))).toBe(false);
  expect(preparationError(new ReconstructionResponseError(500,'route_preparation_attempt_quota'))).toMatch(/Ответ не подтверждён/);
});
test('manual preparation mirrors the stricter temporal gate even without a summary warning',()=>{
  expect(cameraMotionRequiresReview({warning:null,rapid_reversals:1,speed_outliers:0})).toBe(true);
  expect(cameraMotionRequiresReview({warning:null,rapid_reversals:0,speed_outliers:1})).toBe(true);
  expect(cameraMotionRequiresReview({warning:null,rapid_reversals:0,speed_outliers:0})).toBe(false);
});
