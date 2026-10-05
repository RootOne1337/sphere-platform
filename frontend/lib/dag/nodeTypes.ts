import { type NodeTypes } from '@xyflow/react';
import { TapNode } from '@/components/sphere/dag/TapNode';
import { SwipeNode } from '@/components/sphere/dag/SwipeNode';
import { SleepNode } from '@/components/sphere/dag/SleepNode';
import { LuaNode } from '@/components/sphere/dag/LuaNode';
import { ConditionNode } from '@/components/sphere/dag/ConditionNode';
import { StartNode } from '@/components/sphere/dag/StartNode';
import { EndNode } from '@/components/sphere/dag/EndNode';
import { ScreenshotNode } from '@/components/sphere/dag/ScreenshotNode';
import { ActionNode } from '@/components/sphere/dag/ActionNode';

export const nodeTypes: NodeTypes = {
  Tap: TapNode,
  Swipe: SwipeNode,
  Sleep: SleepNode,
  Lua: LuaNode,
  Condition: ConditionNode,
  Start: StartNode,
  End: EndNode,
  Screenshot: ScreenshotNode,
  Action: ActionNode,
};

export interface DagNodeData extends Record<string, unknown> {
  type: string;
  action: Record<string, unknown> & { type: string };
  retry?: number;
  timeout_ms?: number;
}
