import type { Node, XYPosition } from '@xyflow/react';
import { ACTION_TYPES } from './export';

export const ACTION_DRAG_TYPE = 'application/x-sphere-studio-action';

/** Retain manual positions, but reserve them before placing newly imported nodes.
 * Explicit drop coordinates remain intentional, including deliberate overlap. */
export function mergeCanvasPositions(arranged: Node[], previous: Node[], placement?: { id: string; x: number; y: number }): Node[] {
  const ids = new Set(arranged.map(node => node.id));
  const positions = new Map(previous.map(node => [node.id, node.position]));
  const occupied = previous.filter(node => ids.has(node.id) && node.id !== placement?.id);
  if (placement) {
    const node = arranged.find(node => node.id === placement.id);
    if (node) occupied.push({ ...node, position: { x: placement.x, y: placement.y } });
  }
  return arranged.map(node => {
    if (node.id === placement?.id) return { ...node, position: { x: placement.x, y: placement.y } };
    const retained = positions.get(node.id);
    if (retained) return { ...node, position: retained };
    const placed = { ...node, position: freeCanvasPosition(occupied, node.position) };
    occupied.push(placed);
    return placed;
  });
}

export function draggedAction(value: string): typeof ACTION_TYPES[number] | null {
  return ACTION_TYPES.includes(value as typeof ACTION_TYPES[number]) ? value as typeof ACTION_TYPES[number] : null;
}

/** Palette clicks search nearby empty cells. A deliberate drop keeps its point.
 * Placement is UI-only and never changes transitions or the executable hash. */
export function freeCanvasPosition(nodes: Node[], origin: XYPosition): XYPosition {
  if (!Number.isFinite(origin.x) || !Number.isFinite(origin.y)) throw new Error('Не получена позиция на схеме.');
  const vacant = (point: XYPosition) => !nodes.some(node => {
    const width = node.measured?.width ?? node.width ?? 256;
    const height = node.measured?.height ?? node.height ?? 132;
    return point.x < node.position.x + width + 24 && point.x + 280 > node.position.x
      && point.y < node.position.y + height + 24 && point.y + 156 > node.position.y;
  });
  if (vacant(origin)) return origin;
  // Bounded at 961 candidates even when the draft contains 500 steps.
  for (let ring = 1; ring <= 15; ring++) for (let y = -ring; y <= ring; y++) for (let x = -ring; x <= ring; x++) {
    if (Math.abs(x) !== ring && Math.abs(y) !== ring) continue;
    const candidate = { x: origin.x + x * 346, y: origin.y + y * 210 };
    if (vacant(candidate)) return candidate;
  }
  throw new Error('Рядом нет свободного места. Перетащите действие в нужную область схемы.');
}
