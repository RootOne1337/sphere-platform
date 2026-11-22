'use client';

import type { VpnScopeMode } from './profileTypes';

/** Shared by single and batch imports: scope must not silently change in either. */
export function VpnTrafficScope({ value, onChange }: { value: VpnScopeMode; onChange: (mode: VpnScopeMode) => void }) {
  return <div className="grid gap-3 sm:col-span-2">
    <label className="grid gap-2 text-sm font-medium">Область VPN
      <select value={value} onChange={e => onChange(e.target.value as VpnScopeMode)} className="min-w-0 rounded-xl border bg-background p-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <option value="selected_apps">Выбранные приложения</option>
        <option value="all_apps_except_control">Все приложения, кроме Sphere</option>
      </select>
    </label>
    <div className="rounded-xl border bg-muted/20 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
      <p className="font-medium text-foreground">Sphere · управление · видео · обновления — напрямую</p>
      <p className="mt-1">{value === 'selected_apps'
        ? 'VPN и блокировка при сбое действуют на указанные приложения. Остальные приложения используют обычную сеть.'
        : 'Все приложения основного пользователя Android, включая установленные позже. При остановке туннеля защита сохраняет блокировку приложений. Режим проходит проверку на Android 8–12; рабочие профили и Android 13+ пока не поддерживаются.'}</p>
      {value === 'all_apps_except_control' && <p className="mt-2">Системные сетевые службы и защита после перезагрузки требуют отдельной проверки. Сохранение профиля не включает VPN.</p>}
    </div>
  </div>;
}
