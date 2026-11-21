import {usableDecision, type Decision} from '../src/features/stream/worldDestination';

const good:Decision={sequence:93,reason:'following',pedal:'throttle',steering:.1,remaining:14,computeMs:48,
  pose:{eye:[-15,24,9],heading:1,supports:37}};
test('only current geometric decisions authorize input',()=>{
  expect(usableDecision(good,93,200,380)).toBe(true);
  expect(usableDecision(good,92,200,380)).toBe(false);
  expect(usableDecision(good,93,200,520)).toBe(false);
  expect(usableDecision(good,93,200,190)).toBe(false);
  for(const change of [{pose:null},{steering:.36},{remaining:NaN},{reason:'confirming_position'},{reason:'stopping'},{reason:'arrived'}])
    expect(usableDecision({...good,...change},93,200,380)).toBe(false);
  expect(usableDecision({...good,reason:'stopping',steering:0,pedal:'brake'},93,200,380)).toBe(true);
});
