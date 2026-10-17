import type { Node, Edge } from '@xyflow/react';

/** Local worker only. No executable DAG edits, no worker survives the request. */
export async function layoutWorkflow(nodes: Node[], edges: Edge[], signal: AbortSignal, direction: 'RIGHT' | 'DOWN' = 'RIGHT'): Promise<Node[]> {
  if (nodes.length > 500) throw new Error('Раскладка ограничена 500 шагами.');
  const { default: ELK } = await import('elkjs/lib/elk-api');
  if (signal.aborted) throw new Error('Раскладка отменена.');
  const worker = new Worker('/vendor/elk/worker-0.12.0.js');
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abort: (() => void) | undefined;
  try {
    const elk = new ELK({ workerFactory: () => worker });
    const cancelled = new Promise<never>((_, reject) => {
      abort = () => reject(new Error('Раскладка отменена.'));
      signal.addEventListener('abort', abort, { once: true });
      timer = setTimeout(() => reject(new Error('ELK не завершил раскладку за 10 секунд. Граф сохранён.')), 10000);
    });
    const graph = await Promise.race([elk.layout({ id: 'root', layoutOptions: {
      'elk.algorithm': 'layered', 'elk.direction': direction, 'elk.spacing.nodeNode': '64',
      'elk.layered.spacing.nodeNodeBetweenLayers': '90', 'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    }, children: nodes.map(node => ({ id: node.id, width: 256, height: 132 })),
    edges: edges.map(edge => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })) }), cancelled]);
    if (signal.aborted) throw new Error('Раскладка отменена.');
    const positions = new Map(graph.children?.map(node => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]));
    return nodes.map(node => ({ ...node, position: positions.get(node.id) ?? node.position }));
  } finally { clearTimeout(timer); if (abort) signal.removeEventListener('abort', abort); worker.terminate(); }
}
