import { type NodeTypes } from '@xyflow/react';
import { WorkflowNode } from '@/components/sphere/dag/WorkflowNode';

export const nodeTypes: NodeTypes = {
  Tap: WorkflowNode, Swipe: WorkflowNode, Sleep: WorkflowNode, Lua: WorkflowNode,
  Condition: WorkflowNode, Start: WorkflowNode, End: WorkflowNode, Screenshot: WorkflowNode, Action: WorkflowNode,
};

export interface DagNodeData extends Record<string, unknown> {
  type: string;
  action: Record<string, unknown> & { type: string };
  retry?: number;
  timeout_ms?: number;
}
