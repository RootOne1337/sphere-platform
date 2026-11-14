import { Handle, Position } from '@xyflow/react';

/** Both wire outcomes stay visible, including imported failure recovery paths. */
export function ActionRoutes() {
  return <>
    <Handle type="source" position={Position.Bottom} title="Успех: on_success" />
    <Handle type="source" position={Position.Right} id="failure" title="Ошибка: on_failure" className="!bg-destructive" />
  </>;
}
