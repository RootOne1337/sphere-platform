'use client';

import { useState } from 'react';
import { History, Search, X } from 'lucide-react';

interface AuditQueryBuilderProps {
  value: string;
  onChange: (value: string) => void;
}

const SUGGESTIONS = ['status:FAILED', 'status:SUCCESS', 'action:LOGIN', 'user:system'];

export function AuditQueryBuilder({ value, onChange }: AuditQueryBuilderProps) {
  const [isFocused, setIsFocused] = useState(false);

  const appendSuggestion = (suggestion: string) => {
    onChange(value ? `${value.trim()} ${suggestion}` : suggestion);
    setIsFocused(false);
  };

  return (
    <div className="relative w-full max-w-2xl" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setIsFocused(false); }}>
      <div className={`flex min-h-10 items-center rounded-lg border bg-background transition-colors ${isFocused ? 'border-ring ring-2 ring-ring/20' : 'border-input'}`}>
        <Search className="ml-3 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          type="search"
          aria-label="Поиск по журналу аудита"
          className="h-10 min-w-0 flex-1 border-0 bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground/75 focus-visible:ring-0"
          placeholder="Поиск · например status:FAILED action:LOGIN"
          value={value}
          maxLength={500}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => setIsFocused(true)}
          onKeyDown={(event) => { if (event.key === 'Escape') setIsFocused(false); }}
        />
        {value && <button type="button" aria-label="Очистить запрос" onClick={() => onChange('')} className="mr-2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"><X className="h-4 w-4" /></button>}
      </div>
      {isFocused && (
        <div className="absolute left-0 right-0 top-full z-50 mt-2 rounded-xl border border-border bg-popover p-2 shadow-xl">
          <p className="flex items-center gap-2 px-2 py-1.5 text-xs font-medium text-muted-foreground"><History className="h-3.5 w-3.5" />Быстрые фильтры</p>
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => appendSuggestion(suggestion)} className="block w-full rounded-lg px-3 py-2 text-left font-mono text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{suggestion}</button>
          ))}
          <p className="px-3 pb-1 pt-2 text-[11px] text-muted-foreground">Поля: <code>status</code>, <code>action</code>, <code>user</code></p>
        </div>
      )}
    </div>
  );
}
