import { type NodeTypes } from '@xyflow/react';
import { TapNode } from '@/components/sphere/dag/TapNode';
import { SwipeNode } from '@/components/sphere/dag/SwipeNode';
import { SleepNode } from '@/components/sphere/dag/SleepNode';
import { LuaNode } from '@/components/sphere/dag/LuaNode';
import { ConditionNode } from '@/components/sphere/dag/ConditionNode';
import { StartNode } from '@/components/sphere/dag/StartNode';
import { EndNode } from '@/components/sphere/dag/EndNode';
import { ScreenshotNode } from '@/components/sphere/dag/ScreenshotNode';

export const nodeTypes: NodeTypes = {
  Tap: TapNode,
  Swipe: SwipeNode,
  Sleep: SleepNode,
  Lua: LuaNode,
  Condition: ConditionNode,
  Start: StartNode,
  End: EndNode,
  Screenshot: ScreenshotNode,
};

export type DagNodeData =
  | { type: 'Tap'; x: number; y: number; description?: string }
  | { type: 'Swipe'; x1: number; y1: number; x2: number; y2: number; duration_ms: number }
  | { type: 'Sleep'; duration_ms: number }
  | { type: 'Lua'; code: string }
  | { type: 'Condition'; condition_expr: string }
  | { type: 'Screenshot'; save_to_results: boolean }
  | { type: 'Start' }
  | { type: 'End' };
