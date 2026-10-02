'use client';

import { useMemo, useRef, useState } from 'react';
import { type Group, useCreateGroup, useUpdateGroup } from '@/lib/hooks/useGroups';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';

export function GroupEditor({ group, groups, available, onClose, onSaved }: {
  group: Group | null;
  groups: Group[];
  available: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Capture the selected owner's metadata once. Background counts must not reset a dirty form.
  const [name, setName] = useState(group?.name ?? '');
  const [description, setDescription] = useState(group?.description ?? '');
  const initialColor = group?.color ?? '#3B82F6';
  const [color, setColor] = useState(initialColor);
  const [parentId, setParentId] = useState(group?.parent_group_id ?? '');
  const parents = useMemo(() => {
    const links = new Map(groups.map((item) => [item.id, item.parent_group_id]));
    return groups.filter((candidate) => {
      const visited = new Set<string>();
      let current: string | null = candidate.id;
      while (current !== null) {
        if (current === group?.id || visited.has(current) || !links.has(current)) return false;
        visited.add(current); current = links.get(current) ?? null;
      }
      return true;
    });
  }, [groups, group?.id]);
  const parentAvailable = !parentId || parents.some((item) => item.id === parentId);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const create = useCreateGroup();
  const update = useUpdateGroup();
  const pending = create.isPending || update.isPending;
  const changed = !group || name.trim() !== group.name || description.trim() !== (group.description ?? '') || color !== initialColor || parentId !== (group.parent_group_id ?? '');
  const valid = name.trim().length > 0 && name.trim().length <= 255 && description.length <= 1000 && /^#[0-9a-f]{6}$/i.test(color);
  const canSubmit = available && parentAvailable && valid && changed && !pending;

  async function submit() {
    if (!canSubmit || lock.current) return;
    lock.current = true; setError(null);
    try {
      if (group) {
        await update.mutateAsync({ groupId: group.id,
          ...(name.trim() !== group.name ? { name: name.trim() } : {}),
          ...(description.trim() !== (group.description ?? '') ? { description: description.trim() } : {}),
          ...(color !== initialColor ? { color } : {}),
          ...(parentId !== (group.parent_group_id ?? '') ? { parent_group_id: parentId || null } : {}),
        });
      } else {
        await create.mutateAsync({ name: name.trim(), description: description.trim() || undefined, color,
          ...(parentId ? { parent_group_id: parentId } : {}),
        });
      }
      onSaved();
    } catch (failure) {
      setError(getApiErrorMessage(failure, failure instanceof Error ? failure.message
        : 'Результат команды не подтверждён. Проверьте каталог и права доступа перед повторной командой.'));
    } finally { lock.current = false; }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !lock.current) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{group ? `Изменить группу «${group.name}»` : 'Новая группа'}</DialogTitle>
          <DialogDescription>{group ? 'Изменяются только заполненные вами поля группы. Назначения устройств сохраняются.' : 'Группа объединяет устройства вашей организации.'}</DialogDescription>
        </DialogHeader>
        {group && <p className="break-all rounded-lg bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">ID: {group.id}</p>}
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="space-y-2"><Label htmlFor="group-name">Название</Label>
            <Input id="group-name" value={name} maxLength={255} autoComplete="off" disabled={pending} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="space-y-2"><Label htmlFor="group-description">Описание · необязательно</Label>
            <Input id="group-description" value={description} maxLength={1000} disabled={pending} onChange={(event) => setDescription(event.target.value)} />
          </div>
          <div className="space-y-2"><Label htmlFor="group-color">Цвет метки</Label>
            <div className="flex items-center gap-3 rounded-lg border border-border p-2.5">
              <input id="group-color" type="color" value={color} disabled={pending} onChange={(event) => setColor(event.target.value)} className="h-9 w-11 cursor-pointer rounded border-0 bg-transparent p-0 disabled:cursor-wait" />
              <span className="font-mono text-sm text-muted-foreground">{color.toUpperCase()}</span>
            </div>
          </div>
          <div className="space-y-2"><Label htmlFor="group-parent">Родительская группа</Label>
            <select id="group-parent" value={parentId} disabled={pending || !available} aria-describedby="group-parent-help"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              onChange={(event) => setParentId(event.target.value)}>
              <option value="">Без родительской группы</option>
              {!parentAvailable && <option value={parentId} disabled>Недоступная связь · {parentId}</option>}
              {parents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <p id="group-parent-help" className="text-xs leading-5 text-muted-foreground">Иерархия групп не перемещает устройства. Собственная группа, потомки и некорректные цепочки исключены.</p>
            {!parentAvailable && <p role="alert" className="text-sm text-destructive">Родительская связь недоступна. Выберите допустимую группу или явно снимите связь.</p>}
          </div>
          {!available && <p role="alert" className="text-sm text-destructive">Группа или каталог сейчас недоступны. Обновите данные перед сохранением.</p>}
          {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" disabled={pending} onClick={onClose}>Отмена</Button>
            <Button type="submit" disabled={!canSubmit}>{pending ? 'Сохраняем…' : group ? 'Сохранить изменения' : 'Создать группу'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
