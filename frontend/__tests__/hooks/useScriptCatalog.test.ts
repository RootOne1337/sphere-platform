import { act, renderHook, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { SessionChangedError, useAuthStore } from '@/lib/store';
import { parseScriptCatalog, ScriptCatalogContractError, useScriptCatalog, useScriptCatalogSource } from '@/lib/hooks/useScriptCatalog';
import { createTestQueryClient, createWrapper } from '../helpers';
import { catalogActor, catalogEnvelope, catalogOrg, catalogScript, catalogSource } from '../scripts/catalog-fixtures';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
beforeEach(() => {
  jest.resetAllMocks();
  useAuthStore.setState({ user: catalogActor, sessionVersion: 0 });
});

describe('metadata catalog parser', () => {
  it('accepts canonical metadata without DAG and keeps zero distinct from an absent version', () => {
    expect(parseScriptCatalog(catalogEnvelope(), catalogOrg)).toEqual(catalogEnvelope());
    const emptySource = { ...catalogScript, node_count: 0 };
    expect(parseScriptCatalog(catalogEnvelope([emptySource]), catalogOrg).items[0].node_count).toBe(0);
    const unpublished = { ...catalogScript, current_version_id: null, current_version: null, node_count: null };
    expect(parseScriptCatalog(catalogEnvelope([unpublished]), catalogOrg).items[0].node_count).toBeNull();
    expect(JSON.stringify(catalogEnvelope())).not.toMatch(/"dag"|"notes"|"versions"|"created_by_id"/);
  });
  it('accepts empty catalogs and pages beyond the end with their authoritative total', () => {
    expect(parseScriptCatalog(catalogEnvelope([], 0), catalogOrg).pages).toBe(0);
    expect(parseScriptCatalog(catalogEnvelope([], 51, 3), catalogOrg, { page: 3 }).total).toBe(51);
  });
  it.each([
    ['legacy array', [catalogScript]],
    ['missing schema', { ...catalogEnvelope(), catalog_schema: undefined }],
    ['unknown schema', { ...catalogEnvelope(), catalog_schema: 2 }],
    ['incorrect total', { ...catalogEnvelope(), total: 2 }],
    ['incorrect pages', { ...catalogEnvelope(), pages: 2 }],
    ['incorrect page', { ...catalogEnvelope(), page: 2 }],
    ['incorrect page size', { ...catalogEnvelope(), per_page: 25 }],
    ['negative total', { ...catalogEnvelope(), total: -1 }],
    ['extra source field', { ...catalogEnvelope(), dag: {} }],
  ])('rejects an invalid envelope: %s', (_name, value) => {
    expect(() => parseScriptCatalog(value, catalogOrg)).toThrow(ScriptCatalogContractError);
  });
  it.each([
    ['invalid script UUID', { id: 'script-1' }],
    ['foreign organization', { org_id: '77777777-7777-4777-8777-777777777777' }],
    ['archived item in active catalog', { is_archived: true }],
    ['missing pointer', { current_version_id: undefined }],
    ['missing count', { node_count: undefined }],
    ['unknown published count', { node_count: null }],
    ['negative count', { node_count: -1 }],
    ['fractional count', { node_count: 1.5 }],
    ['unsafe count', { node_count: Number.MAX_SAFE_INTEGER + 1 }],
    ['pointer mismatch', { current_version_id: '55555555-5555-4555-8555-555555555555' }],
    ['wrong script owner', { current_version: { ...catalogScript.current_version, script_id: '55555555-5555-4555-8555-555555555555' } }],
    ['version number zero', { current_version: { ...catalogScript.current_version, version: 0 } }],
    ['uppercase hash', { current_version: { ...catalogScript.current_version, dag_hash: 'A'.repeat(64) } }],
    ['missing hash', { current_version: { ...catalogScript.current_version, dag_hash: null } }],
    ['source leaked in version', { current_version: { ...catalogScript.current_version, dag: {} } }],
    ['source leaked at script level', { dag: {} }],
    ['history leaked', { versions: [] }],
    ['missing version object', { current_version: null }],
    ['unpublished count supplied', { current_version_id: null, current_version: null, node_count: 0 }],
    ['unpublished version supplied', { current_version_id: null, node_count: null }],
    ['invalid timestamp', { updated_at: 'yesterday' }],
  ])('rejects invalid item metadata: %s', (_name, patch) => {
    expect(() => parseScriptCatalog(catalogEnvelope([{ ...catalogScript, ...patch } as never]), catalogOrg)).toThrow(ScriptCatalogContractError);
  });
  it('rejects duplicate rows and accepts archived metadata only when requested', () => {
    expect(() => parseScriptCatalog(catalogEnvelope([catalogScript, catalogScript]), catalogOrg)).toThrow(ScriptCatalogContractError);
    const archived = { ...catalogScript, is_archived: true };
    expect(parseScriptCatalog(catalogEnvelope([archived]), catalogOrg, { state: 'archived' }).items[0]).toEqual(archived);
    expect(parseScriptCatalog(catalogEnvelope([archived]), catalogOrg, { state: 'all' }).items[0]).toEqual(archived);
  });
});

describe('scoped catalog requests', () => {
  it('reads only /scripts/catalog with AbortSignal and a separate scoped query cache', async () => {
    const qc = createTestQueryClient();
    jest.mocked(api.get).mockResolvedValue({ data: catalogEnvelope() } as never);
    const { result } = renderHook(() => useScriptCatalog({ page: 1, per_page: 50 }), { wrapper: createWrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.get).toHaveBeenCalledWith('/scripts/catalog', { params: { page: 1, per_page: 50 }, signal: expect.any(AbortSignal) });
    expect(qc.getQueryCache().getAll()[0].queryKey).toEqual(['scripts', 'catalog', {
      orgId: catalogOrg, userId: catalogActor.id, role: catalogActor.role, session: 0,
    }, { page: 1, per_page: 50 }]);
    expect(api.get).toHaveBeenCalledTimes(1);
  });
  it.each([
    { response: { status: 404 } },
    { response: { status: 503, data: { detail: { code: 'script_catalog_metadata_unavailable' } } } },
  ])('fails closed on unavailable API without legacy or source fallback (%j)', async error => {
    jest.mocked(api.get).mockRejectedValue(error);
    const { result } = renderHook(() => useScriptCatalog(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(jest.mocked(api.get).mock.calls[0][0]).toBe('/scripts/catalog');
  });
  it('rejects a malformed response without trying the full list', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...catalogEnvelope(), items: [{ ...catalogScript, node_count: null }] } } as never);
    const { result } = renderHook(() => useScriptCatalog(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(ScriptCatalogContractError));
    expect(api.get).toHaveBeenCalledTimes(1);
  });
  it('does not request data until an actor is known', () => {
    useAuthStore.setState({ user: null });
    renderHook(() => useScriptCatalog(), { wrapper: createWrapper() });
    expect(api.get).not.toHaveBeenCalled();
  });
  it('rejects a manual refetch before an actor is known without issuing any request', async () => {
    useAuthStore.setState({ user: null });
    const { result } = renderHook(() => useScriptCatalog(), { wrapper: createWrapper() });
    await act(async () => {
      const receipt = await result.current.refetch();
      expect(receipt.error).toBeInstanceOf(SessionChangedError);
    });
    expect(result.current.data).toBeUndefined();
    expect(api.get).not.toHaveBeenCalled();
  });
  it('cancels a retired session and rejects its late tenant response even when the HTTP mock ignores abort', async () => {
    const qc = createTestQueryClient();
    let finish!: (value: unknown) => void;
    const pending = new Promise(resolve => { finish = resolve; });
    jest.mocked(api.get).mockReturnValue(pending as never);
    const { result } = renderHook(() => useScriptCatalog(), { wrapper: createWrapper(qc) });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    const signal = jest.mocked(api.get).mock.calls[0][1]?.signal;
    const foreignOrg = '77777777-7777-4777-8777-777777777777';
    act(() => useAuthStore.setState({ user: { ...catalogActor, org_id: foreignOrg }, sessionVersion: 1 }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    await act(async () => { finish({ data: catalogEnvelope() }); });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(signal?.aborted).toBe(true);
    expect(result.current.data).toBeUndefined();
    expect(qc.getQueryCache().getAll().every(query => query.state.data === undefined)).toBe(true);
  });
});

describe('pinned catalog source', () => {
  it('reads one owned version and verifies its catalog receipt without requesting detail/history', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: catalogSource } as never);
    const { result } = renderHook(() => useScriptCatalogSource(catalogScript), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith(`/scripts/${catalogScript.id}/versions/${catalogSource.id}`, { signal: expect.any(AbortSignal) });
    expect(result.current.data).toEqual(catalogSource);
  });
  it('checks a changed metadata count instead of reusing an accepted source with the same version ID and hash', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: catalogSource } as never);
    const { result, rerender } = renderHook(({ script }) => useScriptCatalogSource(script), { wrapper: createWrapper(), initialProps: { script: catalogScript } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.get).toHaveBeenCalledTimes(1);
    rerender({ script: { ...catalogScript, node_count: 1 } });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBeInstanceOf(ScriptCatalogContractError);
    expect(result.current.data).toBeUndefined();
  });
  it.each([
    ['wrong version', { id: '55555555-5555-4555-8555-555555555555' }],
    ['wrong owner', { script_id: '55555555-5555-4555-8555-555555555555' }],
    ['wrong hash', { dag_hash: 'b'.repeat(64) }],
    ['wrong number', { version: 5 }],
    ['wrong source count', { dag: { nodes: [{}] } }],
    ['missing source', { dag: undefined }],
    ['null source', { dag: null }],
  ])('rejects an unconfirmed source: %s', async (_name, patch) => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...catalogSource, ...patch } } as never);
    const { result } = renderHook(() => useScriptCatalogSource(catalogScript), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(api.get).toHaveBeenCalledTimes(1);
  });
  it('ignores a late source after a different pinned version is selected', async () => {
    let finish!: (value: unknown) => void;
    const nextId = '55555555-5555-4555-8555-555555555555';
    const next = { ...catalogScript, current_version_id: nextId, current_version: { ...catalogScript.current_version!, id: nextId, version: 5, dag_hash: 'b'.repeat(64) } };
    jest.mocked(api.get).mockImplementation(url => url.endsWith(nextId)
      ? Promise.resolve({ data: { ...catalogSource, ...next.current_version } }) as never
      : new Promise(resolve => { finish = resolve; }) as never);
    const { result, rerender } = renderHook(({ script }) => useScriptCatalogSource(script), { wrapper: createWrapper(), initialProps: { script: catalogScript } });
    await waitFor(() => expect(finish).toBeDefined());
    const signal = jest.mocked(api.get).mock.calls[0][1]?.signal;
    rerender({ script: next });
    await waitFor(() => expect(result.current.data?.id).toBe(nextId));
    await act(async () => { finish({ data: catalogSource }); });
    expect(signal?.aborted).toBe(true);
    expect(result.current.data?.id).toBe(nextId);
  });
  it('does not read source for an unpublished or foreign script', () => {
    renderHook(() => useScriptCatalogSource({ ...catalogScript, current_version: null, current_version_id: null, node_count: null }), { wrapper: createWrapper() });
    renderHook(() => useScriptCatalogSource({ ...catalogScript, org_id: 'foreign' }), { wrapper: createWrapper() });
    expect(api.get).not.toHaveBeenCalled();
  });
});
