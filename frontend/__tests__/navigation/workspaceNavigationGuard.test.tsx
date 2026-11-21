import { StrictMode } from 'react';
import { act, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { navigateFromWorkspace, registerWorkspaceLeaveGuard, useWorkspaceNavigationGuard, workspaceNavigationAllowed } from '@/src/features/navigation/workspaceNavigationGuard';

const navigate = jest.fn();
function Harness({ guard }: { guard: () => boolean | Promise<boolean> }) {
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

function pendingDecision() {
  let resolve!: (allow: boolean) => void;
  const promise = new Promise<boolean>(done => { resolve = done; });
  return { promise, resolve };
}

it('defers an ordinary link and resumes its handler exactly once after approval', async () => {
  const decision = pendingDecision(), guard = jest.fn(() => decision.promise);
  const view = render(<Harness guard={guard} />);
  fireEvent.click(screen.getByTestId('icon')); expect(navigate).not.toHaveBeenCalled();
  await act(async () => decision.resolve(true));
  await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1)); expect(guard).toHaveBeenCalledTimes(1);
  view.unmount();
});

it.each(['cancel', 'unmount', 'replace-link'])('never replays a canceled or retired navigation (%s)', async reason => {
  const decision = pendingDecision(); const view = render(<Harness guard={() => decision.promise} />);
  fireEvent.click(screen.getByTestId('icon'));
  if (reason === 'unmount') view.unmount();
  if (reason === 'replace-link') screen.getByTestId('icon').closest('a')!.href = '/users';
  await act(async () => decision.resolve(reason !== 'cancel'));
  expect(navigate).not.toHaveBeenCalled(); view.unmount();
});

it('cancels programmatic navigation if any owner changed while another decision was pending', async () => {
  const decision = pendingDecision(), perform = jest.fn();
  const first = registerWorkspaceLeaveGuard(() => true), second = registerWorkspaceLeaveGuard(() => decision.promise);
  try {
    navigateFromWorkspace(perform); first();
    const replacement = registerWorkspaceLeaveGuard(() => true);
    try { await act(async () => decision.resolve(true)); expect(perform).not.toHaveBeenCalled(); }
    finally { replacement(); }
  } finally { first(); second(); }
});

it('treats an asynchronously rejected decision as cancellation without running side effects', async () => {
  const perform = jest.fn(); const remove = registerWorkspaceLeaveGuard(() => Promise.reject(new Error('failed dialog')));
  try { navigateFromWorkspace(perform); await act(async () => undefined); expect(perform).not.toHaveBeenCalled(); }
  finally { remove(); }
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
