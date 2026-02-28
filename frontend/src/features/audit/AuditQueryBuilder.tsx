'use client';

import { useState } from 'react';
import { Search, History, X } from 'lucide-react';

interface AuditQueryBuilderProps {
    value: string;
    onChange: (val: string) => void;
}

const SUGGESTIONS = [
    'status:FAILED',
    'status:SUCCESS',
    'action:LOGIN_ATTEMPT',
    'action:VPN_TUNNEL_DROP',
    'user:admin@sphere.local'
];

export function AuditQueryBuilder({ value, onChange }: AuditQueryBuilderProps) {
    const [isFocused, setIsFocused] = useState(false);

    const handleSuggestionClick = (suggestion: string) => {
        // Добавляем пробел если уже что-то введено
        const newVal = value ? `${value} ${suggestion}` : suggestion;
        onChange(newVal);
        setIsFocused(false);
    };

    const clearQuery = () => {
        onChange('');
    };

    return (
        <div className="relative w-[450px]">
            <div className={`flex items-center bg-card border rounded-sm transition-colors ${isFocused ? 'border-primary ring-1 ring-primary/30' : 'border-border'}`}>
                <div className="pl-3 pr-2 py-2 flex items-center justify-center text-muted-foreground shrink-0 border-r border-border">
                    <Search className="w-4 h-4" />
                </div>
                <input
                    type="text"
                    className="w-full bg-transparent border-none outline-none text-xs font-mono px-3 py-2 text-foreground placeholder:text-[#555]"
                    placeholder="e.g. status:FAILED action:VPN_DROP user:admin"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onFocus={() => setIsFocused(true)}
                    onBlur={() => setTimeout(() => setIsFocused(false), 200)} // Задержка чтобы успеть кликнуть на саджест
                />
                {value && (
                    <button onClick={clearQuery} className="px-3 py-2 text-muted-foreground hover:text-foreground">
                        <X className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>

            {/* Suggestions Dropdown */}
            {isFocused && (
                <div className="absolute top-full left-0 w-full mt-1 bg-muted border border-border rounded-sm shadow-2xl z-50 py-1">
                    <div className="px-3 py-1.5 text-[10px] uppercase font-bold tracking-widest text-[#555] flex items-center gap-1.5">
                        <History className="w-3 h-3" /> Filters & Suggestions
                    </div>
                    {SUGGESTIONS.map(s => (
                        <div
                            key={s}
                            className="px-4 py-2 text-xs font-mono text-muted-foreground hover:bg-primary/10 hover:text-primary cursor-pointer transition-colors"
                            onClick={() => handleSuggestionClick(s)}
                        >
                            {s}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
