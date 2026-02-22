'use client';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Plus } from 'lucide-react';

interface Script {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  node_count: number;
}

export default function ScriptsPage() {
  const { data: scripts, isLoading } = useQuery<Script[]>({
    queryKey: ['scripts'],
    queryFn: async () => {
      const { data } = await api.get('/scripts');
      return data;
    },
  });

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
    </div>
  );
}
