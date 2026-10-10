import { parseListItems } from '@/src/features/orchestration/listPayload';

it('accepts the paginated API envelope and returns its item collection', () => {
  expect(parseListItems({ items: [{ id: 'pipeline-1' }] }, 'pipelines')).toEqual([{ id: 'pipeline-1' }]);
});

it.each([null, [], {}, { items: null }, { items: 'not-an-array' }])(
  'rejects malformed list payloads instead of presenting them as an empty catalog: %s',
  (payload) => {
    expect(() => parseListItems(payload, 'pipelines')).toThrow('Invalid pipelines list response');
  },
);
