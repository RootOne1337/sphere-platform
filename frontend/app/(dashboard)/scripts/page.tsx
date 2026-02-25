'use client';
import { useState } from 'react';
import Link from 'next/link';
import { Play, Plus } from 'lucide-react';
import { useScripts } from '@/lib/hooks/useScripts';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';

export default function ScriptsPage() {
  const { data: scripts, isLoading } = useScripts();
  const [runTarget, setRunTarget] = useState<{ id: string; name: string } | null>(null);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Scripts</h1>
        <Button asChild>
          <Link href="/scripts/builder">
            <Plus className="w-4 h-4 mr-2" />
            New Script
          </Link>
        </Button>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <div className="space-y-2">
          {scripts?.map((script) => (
            <div
              key={script.id}
              className="flex items-center justify-between p-4 rounded border hover:bg-accent/50 transition-colors"
            >
              <div>
                <p className="font-medium">{script.name}</p>
                <p className="text-xs text-muted-foreground">
                  Updated {new Date(script.updated_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline">{script.node_count} nodes</Badge>
                <Button
                  size="sm"
                  variant="default"
                  className="gap-1.5 bg-green-600 hover:bg-green-700"
                  onClick={() => setRunTarget({ id: script.id, name: script.name })}
                >
                  <Play className="w-3 h-3" />
                  Run
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link href={`/scripts/builder?id=${script.id}`}>Edit</Link>
                </Button>
              </div>
            </div>
          ))}
          {scripts?.length === 0 && (
            <p className="text-muted-foreground text-sm text-center py-10">
              No scripts yet. Create your first one!
            </p>
          )}
        </div>
      )}

      {runTarget && (
        <RunScriptModal
          scriptId={runTarget.id}
          scriptName={runTarget.name}
          open={true}
          onClose={() => setRunTarget(null)}
        />
      )}
    </div>
  );
}
