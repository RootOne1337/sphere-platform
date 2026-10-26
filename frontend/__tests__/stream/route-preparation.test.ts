import {prepareRoute,preparationError} from '@/src/features/stream/routePreparation';
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
