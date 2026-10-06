import type { Node, XYPosition } from '@xyflow/react';
import { ACTION_TYPES } from './export';

export const ACTION_DRAG_TYPE = 'application/x-sphere-studio-action';
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
