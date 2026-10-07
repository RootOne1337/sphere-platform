import { StrictMode } from 'react';
import { createEvent, fireEvent, render, screen } from '@testing-library/react';
import { registerWorkspaceLeaveGuard, useWorkspaceNavigationGuard, workspaceNavigationAllowed } from '@/src/features/navigation/workspaceNavigationGuard';

const navigate = jest.fn();
function Harness({ guard }: { guard: () => boolean }) {
  useWorkspaceNavigationGuard(guard);
  return <div><a href="/devices" onClick={event => { event.preventDefault(); navigate(); }}><svg data-testid="icon" /></a></div>;
}
beforeEach(() => { navigate.mockReset(); window.history.replaceState({}, '', '/scripts/builder?id=a'); });

it('blocks an ordinary link before its Next/mobile handlers and uses the current decision', () => {
  const old = jest.fn(() => false), next = jest.fn(() => true);
  const view = render(<Harness guard={old} />);
  fireEvent.click(screen.getByTestId('icon'));
  expect(old).toHaveBeenCalledTimes(1); expect(navigate).not.toHaveBeenCalled();
  view.rerender(<Harness guard={next} />);
  fireEvent.click(screen.getByTestId('icon'));
  expect(old).toHaveBeenCalledTimes(1); expect(next).toHaveBeenCalledTimes(1); expect(navigate).toHaveBeenCalledTimes(1);
  view.unmount(); expect(workspaceNavigationAllowed()).toBe(true);
});

it('covers links outside the workspace, including a portaled menu', () => {
  const guard = jest.fn(() => false);
  const view = render(<Harness guard={guard} />);
  const anchor = document.createElement('a'); anchor.href = '/tasks';
  const follow = jest.fn((event: MouseEvent) => event.preventDefault());
  anchor.addEventListener('click', follow); document.body.append(anchor);
  fireEvent.click(anchor);
  expect(guard).toHaveBeenCalledTimes(1); expect(follow).not.toHaveBeenCalled();
  anchor.remove(); view.unmount();
});

it.each([{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }])('keeps opening another tab/window available (%j)', options => {
  const guard = jest.fn(() => false); const view = render(<Harness guard={guard} />);
  fireEvent.click(screen.getByTestId('icon'), options);
  expect(guard).not.toHaveBeenCalled(); view.unmount();
});

it.each([
  { href: '/scripts/builder?id=a#step' },
  { href: '/devices', target: '_blank' },
  { href: '/devices', target: 'other-window' },
  { href: 'blob:http://localhost/export', download: 'graph.json' },
  { href: 'mailto:operator@example.com' },
])('preserves in-page jumps, downloads and other browsing contexts (%j)', options => {
  const guard = jest.fn(() => false); const view = render(<Harness guard={guard} />);
  const anchor = document.createElement('a');
  Object.assign(anchor, options); anchor.addEventListener('click', event => event.preventDefault()); document.body.append(anchor);
  fireEvent.click(anchor); expect(guard).not.toHaveBeenCalled(); anchor.remove(); view.unmount();
});

it.each(['/scripts/builder?id=b', 'https://example.com/'])('guards replacement of the script or current document (%s)', href => {
  const guard = jest.fn(() => false); const view = render(<Harness guard={guard} />);
  const anchor = document.createElement('a'); anchor.href = href;
  anchor.addEventListener('click', event => event.preventDefault()); document.body.append(anchor);
  fireEvent.click(anchor); expect(guard).toHaveBeenCalledTimes(1); anchor.remove(); view.unmount();
});

it('does not reconsider a click already canceled by another capture listener', () => {
  const cancel = (event: MouseEvent) => event.preventDefault();
  document.addEventListener('click', cancel, true);
  const guard = jest.fn(() => false); const view = render(<Harness guard={guard} />);
  const event = createEvent.click(screen.getByTestId('icon'));
  fireEvent(screen.getByTestId('icon'), event); expect(guard).not.toHaveBeenCalled();
  view.unmount(); document.removeEventListener('click', cancel, true);
});

it('isolates registration cleanup and fails closed if a mounted guard throws', () => {
  const first = jest.fn(() => true), second = jest.fn(() => false);
  const removeFirst = registerWorkspaceLeaveGuard(first), removeSecond = registerWorkspaceLeaveGuard(second);
  try {
    expect(workspaceNavigationAllowed()).toBe(false);
    removeFirst(); removeFirst(); first.mockClear();
    expect(workspaceNavigationAllowed()).toBe(false); expect(first).not.toHaveBeenCalled();
    removeSecond();
    const removeBroken = registerWorkspaceLeaveGuard(() => { throw new Error('failed guard'); });
    try { expect(workspaceNavigationAllowed()).toBe(false); } finally { removeBroken(); }
    expect(workspaceNavigationAllowed()).toBe(true);
  } finally { removeFirst(); removeSecond(); }
});

it('registers once after StrictMode remount and cleans up the capture listener', () => {
  const guard = jest.fn(() => false); const view = render(<StrictMode><Harness guard={guard} /></StrictMode>);
  fireEvent.click(screen.getByTestId('icon')); expect(guard).toHaveBeenCalledTimes(1);
  view.unmount(); expect(workspaceNavigationAllowed()).toBe(true);
});
