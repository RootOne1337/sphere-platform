import type { StreamFrameDimensions } from './streamAspectRatio';

export interface UiBounds { left: number; top: number; right: number; bottom: number }
export interface UiHierarchyNode {
  id: number; parent_id: number | null; depth: number; xpath: string;
  attributes: Record<string, string>; bounds: UiBounds | null;
}
export interface UiHierarchySnapshot {
  device_id: string; snapshot_id: string; requested_at: string; completed_at: string;
  source: 'android_uiautomator_root'; width: number; height: number; rotation: number;
  temporary_file_cleanup_confirmed: boolean;
  nodes: UiHierarchyNode[];
}

export function checkedHierarchy(value: unknown, deviceId: string): UiHierarchySnapshot {
  if (!value || typeof value !== 'object') throw new Error('Неполный ответ дерева Android.');
  const data = value as UiHierarchySnapshot;
  if (data.device_id !== deviceId || !/^[a-f0-9]{32}$/.test(data.snapshot_id ?? '')
    || data.source !== 'android_uiautomator_root'
    || typeof data.temporary_file_cleanup_confirmed !== 'boolean'
    || !Number.isInteger(data.width) || data.width < 1 || data.width > 16384
    || !Number.isInteger(data.height) || data.height < 1 || data.height > 16384
    || !Number.isInteger(data.rotation) || data.rotation < 0 || data.rotation > 3
    || !Number.isFinite(Date.parse(data.requested_at)) || !Number.isFinite(Date.parse(data.completed_at))
    || Date.parse(data.completed_at) < Date.parse(data.requested_at)
    || !Array.isArray(data.nodes) || data.nodes.length > 4096) throw new Error('Дерево не принадлежит выбранному устройству или имеет неверную геометрию.');
  for (let index = 0; index < data.nodes.length; index++) {
    const node = data.nodes[index];
    if (!node || node.id !== index || !Number.isInteger(node.depth) || node.depth < 0 || node.depth >= 64
      || !(node.parent_id === null || Number.isInteger(node.parent_id) && node.parent_id >= 0 && node.parent_id < index)
      || typeof node.xpath !== 'string' || !/^\/hierarchy(?:\/node\[\d+\])+$/.test(node.xpath)
      || !node.attributes || typeof node.attributes !== 'object' || Array.isArray(node.attributes)
      || Object.entries(node.attributes).length > 64
      || Object.entries(node.attributes).some(([key, text]) => key.length > 128 || typeof text !== 'string' || text.length > 4096)) throw new Error('Некорректный элемент дерева Android.');
    if (node.bounds && (![node.bounds.left, node.bounds.top, node.bounds.right, node.bounds.bottom].every(Number.isInteger)
      || node.bounds.left < 0 || node.bounds.top < 0 || node.bounds.right > data.width || node.bounds.bottom > data.height
      || node.bounds.left >= node.bounds.right || node.bounds.top >= node.bounds.bottom)) throw new Error('Некорректные границы элемента Android.');
  }
  return data;
}

export function matchesFrame(snapshot: UiHierarchySnapshot, frame: StreamFrameDimensions | null): boolean {
  return !!frame && frame.width > 0 && frame.height > 0
    && Math.abs((frame.width / frame.height) / (snapshot.width / snapshot.height) - 1) < 0.01;
}

/** Prefer the deepest visible descendant, then the smallest overlapping region. */
export function hitTestHierarchy(snapshot: UiHierarchySnapshot, x: number, y: number): UiHierarchyNode | null {
  return snapshot.nodes.filter(node => node.bounds && x >= node.bounds.left && x < node.bounds.right
    && y >= node.bounds.top && y < node.bounds.bottom).sort((a, b) => b.depth - a.depth
      || ((a.bounds!.right - a.bounds!.left) * (a.bounds!.bottom - a.bounds!.top))
      - ((b.bounds!.right - b.bounds!.left) * (b.bounds!.bottom - b.bounds!.top)))[0] ?? null;
}

export function frameBounds(bounds: UiBounds, snapshot: UiHierarchySnapshot, frame: StreamFrameDimensions): UiBounds {
  return { left: bounds.left * frame.width / snapshot.width, right: bounds.right * frame.width / snapshot.width,
    top: bounds.top * frame.height / snapshot.height, bottom: bounds.bottom * frame.height / snapshot.height };
}
