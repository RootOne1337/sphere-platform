import type { Connection, Edge, Node } from '@xyflow/react';

export const OUTLET_LABELS: Record<string, string> = {
  next: 'Успех · on_success', failure: 'Ошибка · on_failure',
  true_branch: 'Да · on_true', false_branch: 'Нет · on_false',
};

export function connectionOutlets(node: Node): Array<string | null> {
  const type = (node.data.action as { type?: string } | undefined)?.type;
  if (type === 'end') return [];
  return type === 'condition' ? ['true_branch', 'false_branch', 'failure'] : [null, 'failure'];
}

/** Validate one canvas edit, including temporarily disconnected drafts. */
export function checkConnection(nodes: Node[], edges: Edge[], connection: Connection, replacingId?: string): void {
  const source = nodes.find(node => node.id === connection.source);
  const target = nodes.find(node => node.id === connection.target);
  if (!source || !target) throw new Error('Выберите существующие шаги для обоих концов связи.');
  if ((target.data.action as { type?: string } | undefined)?.type === 'start') throw new Error('У начального шага нет входа.');
  if (connection.targetHandle != null) throw new Error('Неизвестный вход шага.');
  const outlet = connection.sourceHandle ?? null;
  // Existing condition.on_success is legal DAG 1.0 even though the visual node
  // normally exposes Yes/No. Preserve that route when moving its target.
  const old = replacingId ? edges.find(edge => edge.id === replacingId) : undefined;
  const legacyOutlet = old?.source === source.id && (old.sourceHandle ?? null) === outlet;
  if (!connectionOutlets(source).includes(outlet) && !(legacyOutlet && outlet === null && (source.data.action as { type?: string })?.type === 'condition')) {
    throw new Error('Этот выход недоступен для выбранного действия.');
  }
  if (edges.some(edge => edge.id !== replacingId && edge.source === source.id && (edge.sourceHandle ?? null) === outlet)) {
    throw new Error('Этот выход уже соединён. Выберите другой выход или разорвите его связь.');
  }
}

export function changeConnection(nodes: Node[], edges: Edge[], id: string, connection: Connection): Edge[] {
  if (!edges.some(edge => edge.id === id)) throw new Error('Связь уже удалена. Выберите существующую связь.');
  checkConnection(nodes, edges, connection, id);
  return edges.map(edge => edge.id === id ? { ...edge, ...connection, sourceHandle: connection.sourceHandle ?? null, targetHandle: null } : edge);
}
