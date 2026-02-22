import { type Node, type Edge } from '@xyflow/react';

export interface DagExport {
  entry_node: string;
  nodes: Record<
    string,
    {
      type: string;
      links: Record<string, string>;
      [key: string]: unknown;
    }
  >;
}

export function exportDag(nodes: Node[], edges: Edge[]): DagExport {
  if (nodes.length === 0) throw new Error('DAG is empty');

  const startNode = nodes.find((n) => n.type === 'Start');
  if (!startNode) throw new Error('DAG must have a Start node');

  // Построить карту связей
  const linksMap: Record<string, Record<string, string>> = {};

  for (const edge of edges) {
    if (!linksMap[edge.source]) linksMap[edge.source] = {};
    const handleKey = edge.sourceHandle ?? 'next';
    linksMap[edge.source][handleKey] = edge.target;
  }

  // Сериализация нод
  const exportNodes: DagExport['nodes'] = {};

  for (const node of nodes) {
    const { type, id, data } = node;
    if (!type) continue;

    exportNodes[id] = {
      type,
      links: linksMap[id] ?? {},
      ...data,
    };
  }

  return {
    entry_node: startNode.id,
    nodes: exportNodes,
  };
}

export function validateDag(dag: DagExport): string[] {
  const errors: string[] = [];
  const nodeIds = new Set(Object.keys(dag.nodes));

  for (const [id, node] of Object.entries(dag.nodes)) {
    for (const [handle, targetId] of Object.entries(node.links)) {
      if (!nodeIds.has(targetId)) {
        errors.push(`Node "${id}" link "${handle}" → unknown node "${targetId}"`);
      }
    }
  }

  const hasEnd = Object.values(dag.nodes).some((n) => n.type === 'End');
  if (!hasEnd) errors.push('DAG must have at least one End node');

  return errors;
}
