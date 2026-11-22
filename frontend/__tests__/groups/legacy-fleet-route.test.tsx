import FleetPage from '@/app/(dashboard)/fleet/page';
import { redirect } from 'next/navigation';
import { render } from '@testing-library/react';
import { createWrapper } from '../helpers';
jest.mock('next/navigation', () => ({ redirect: jest.fn(() => { throw new Error('NEXT_REDIRECT'); }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(async () => ({ data: [] })) } }));
it('redirects the old fleet bookmark to the working group workflow', () => {
  expect(() => render(<FleetPage />, { wrapper: createWrapper() })).toThrow('NEXT_REDIRECT');
  expect(redirect).toHaveBeenCalledWith('/groups');
});
