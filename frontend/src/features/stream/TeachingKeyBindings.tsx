'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { bindTeachingKey, keyLabel, keyRoleNames, keyRoles, teachingKeys, type TeachingKeyRole, type TeachingProfile } from './teachingKeymap';

export function TeachingKeyBindings({profile,disabled,editing,onEditingChange,onChange}:{
  profile:TeachingProfile;disabled:boolean;editing:TeachingKeyRole|null;
  onEditingChange:(role:TeachingKeyRole|null)=>void;onChange:(profile:TeachingProfile)=>void;
}) {
  const [issue,setIssue]=useState<string|null>(null),keys=teachingKeys(profile);
  return <section aria-label="Назначение клавиш" className="space-y-2 rounded-xl border border-border bg-muted/20 p-3">
    <div className="flex items-center justify-between gap-2"><h4 className="text-sm font-medium">Клавиши и зоны</h4>
      <Button size="sm" variant="ghost" disabled={disabled} onClick={()=>{const next={...profile};delete next.keys;onChange(next);onEditingChange(null);setIssue(null);}}>По умолчанию</Button></div>
    <p className="text-xs leading-5 text-muted-foreground">Выберите действие и нажмите клавишу. Экранную зону укажите ниже; нажатия при настройке в Android не отправляются.</p>
    <div className="grid grid-cols-2 gap-2">{keyRoles.map(role=><button type="button" key={role}
      disabled={disabled} aria-label={`Клавиша: ${keyRoleNames[role]}`} aria-pressed={editing===role}
      className={`flex min-h-14 min-w-0 flex-col items-start justify-center gap-1 rounded-lg border px-3 py-2 text-left text-xs disabled:opacity-50 ${editing===role?'border-primary bg-primary/10 ring-2 ring-primary/30':'border-border bg-background'}`}
      onClick={()=>{setIssue(null);onEditingChange(editing===role?null:role);}}
      onKeyDown={event=>{
        if(editing!==role||disabled)return;
        event.preventDefault();event.stopPropagation();
        if(event.code==='Escape'){onEditingChange(null);setIssue(null);return;}
        if(event.repeat)return;
        if(event.ctrlKey||event.altKey||event.metaKey){setIssue('Назначьте одну клавишу без Ctrl, Alt или Meta.');return;}
        try {onChange(bindTeachingKey(profile,role,event.code));onEditingChange(null);setIssue(null);}
        catch(error){setIssue(error instanceof Error?error.message:'Клавиша не назначена.');}
      }}><span className="text-muted-foreground">{keyRoleNames[role]}</span><kbd className="max-w-full truncate font-semibold">{editing===role?'Нажмите клавишу…':keyLabel(keys[role])}</kbd></button>)}</div>
    {(editing||issue)&&<p role="status" className="text-xs leading-5 text-primary">{issue??'Ожидаем клавишу. Escape — отменить назначение.'}</p>}
  </section>;
}
