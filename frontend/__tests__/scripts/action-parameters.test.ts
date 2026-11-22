import fs from 'node:fs';
import path from 'node:path';
import { ACTION_TYPES } from '@/lib/dag/export';
import { actionContract, actionParameterErrors } from '@/lib/dag/actionParameters';
import { defaultAction } from '@/lib/dag/studio';

const root = path.resolve(process.cwd(), '..');
const fixture: { valid_actions: Record<string, Record<string, unknown>>; cases: { name: string; action: Record<string, unknown>; errors: string[] }[] } = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/action-parameters.v1.json'), 'utf8'));
const concise = (action: Record<string, unknown>) => actionParameterErrors([{ action }]).map(error => `${error.loc.slice(3).join('.')}:${error.type.split('.').at(-1)}`);

it.each(Object.entries(fixture.valid_actions))('accepts %s without coercing or rewriting source', (_, action) => {
  const source = JSON.stringify(action);
  expect(concise(action)).toEqual([]);
  expect(JSON.stringify(action)).toBe(source);
});
it.each(fixture.cases)('$name has the same exact paths/codes as Python', ({ action, errors }) => {
  const source = JSON.stringify(action);
  expect(concise(action)).toEqual(errors);
  expect(JSON.stringify(action)).toBe(source);
  expect(JSON.stringify(actionParameterErrors([{ action }]))).not.toContain('PRIVATE');
});
it('matches all published action types and the independent Docker build copy', () => {
  expect(Object.keys(actionContract.actions).sort()).toEqual([...ACTION_TYPES].sort());
  expect(Object.keys(fixture.valid_actions).sort()).toEqual([...ACTION_TYPES].sort());
  expect(fs.readFileSync(path.join(root, 'backend/schemas/action_contract.v1.json'))).toEqual(fs.readFileSync(path.join(root, 'frontend/lib/dag/action-contract.v1.json')));
});
it('validates every library template except the deliberately blank destructive package', () => {
  for (const type of ACTION_TYPES) {
    const action = defaultAction(type);
    if (type === 'condition') Object.assign(action, { on_true: 'end', on_false: 'end' });
    expect(concise(action)).toEqual(type === 'clear_app_data' ? ['package:length'] : []);
  }
});
it('bounds error count, candidate iteration and unicode by codepoints', () => {
  expect(actionParameterErrors(Array.from({ length: 500 }, () => ({ action: { type: 'tap' } })))).toHaveLength(100);
  expect(concise({ type: 'find_first_element', candidates: Array(65).fill({}) })).toEqual(['candidates:length']);
  expect(concise({ type: 'type_text', text: '😀'.repeat(65536) })).toEqual([]);
  expect(concise({ type: 'type_text', text: '😀'.repeat(65537) })).toEqual(['text:length']);
});
it.each([NaN, Infinity, -Infinity])('rejects nonfinite JSON-like values %s', value => {
  expect(concise({ type: 'scroll', percent: value })).toEqual(['percent:number']);
});
