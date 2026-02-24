'use client';
import { useState, useEffect } from 'react';
import { useDevices } from '@/lib/hooks/useDevices';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Release {
  id: string;
  platform: string;
  flavor: string;
  version_code: number;
  version_name: string;
  download_url: string;
  sha256: string;
  mandatory: boolean;
  changelog: string | null;
  created_at: string;
}

interface ReleasesResponse {
  releases: Release[];
  total: number;
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

function useReleases(platform?: string, flavor?: string) {
  const [data, setData] = useState<ReleasesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReleases = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (platform) params.set('platform', platform);
      if (flavor) params.set('flavor', flavor);
      const res = await fetch(`/api/v1/updates/?${params}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchReleases(); }, [platform, flavor]); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error, refetch: fetchReleases };
}

// ── Push OTA command to device/group ─────────────────────────────────────────

async function pushOtaUpdate(deviceId: string, release: Release) {
  const res = await fetch(`/api/v1/tasks/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
    },
    body: JSON.stringify({
      device_id: deviceId,
      type: 'OTA_UPDATE',
      payload: {
        download_url: release.download_url,
        version: release.version_name,
        sha256: release.sha256,
        force: release.mandatory,
      },
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Create Release Form ───────────────────────────────────────────────────────

function CreateReleaseDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    platform: 'android',
    flavor: 'enterprise',
    version_code: '',
    version_name: '',
    download_url: '',
    sha256: '',
    mandatory: false,
    changelog: '',
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch('/api/v1/updates/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
        },
        body: JSON.stringify({
          ...form,
          version_code: parseInt(form.version_code, 10),
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      setOpen(false);
      onCreated();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error creating release');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>+ New Release</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Register New APK Release</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4 py-2">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Platform</Label>
              <Select value={form.platform} onValueChange={(v) => setForm((f) => ({ ...f, platform: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="android">Android</SelectItem>
                  <SelectItem value="pc">PC (Windows)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Flavor</Label>
              <Select value={form.flavor} onValueChange={(v) => setForm((f) => ({ ...f, flavor: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="enterprise">enterprise</SelectItem>
                  <SelectItem value="dev">dev</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Version Code</Label>
              <Input
                type="number"
                required
                placeholder="20260223"
                value={form.version_code}
                onChange={(e) => setForm((f) => ({ ...f, version_code: e.target.value }))}
              />
            </div>
            <div>
              <Label>Version Name</Label>
              <Input
                required
                placeholder="1.5.0"
                value={form.version_name}
                onChange={(e) => setForm((f) => ({ ...f, version_name: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <Label>Download URL (HTTPS only)</Label>
            <Input
              required
              type="url"
              placeholder="https://storage.example.com/sphere-1.5.0.apk"
              value={form.download_url}
              onChange={(e) => setForm((f) => ({ ...f, download_url: e.target.value }))}
            />
          </div>
          <div>
            <Label>SHA-256 Checksum</Label>
            <Input
              placeholder="a3f8... (64 hex chars)"
              value={form.sha256}
              onChange={(e) => setForm((f) => ({ ...f, sha256: e.target.value }))}
            />
          </div>
          <div>
            <Label>Changelog (optional)</Label>
            <Input
              placeholder="Bug fixes, new commands, …"
              value={form.changelog}
              onChange={(e) => setForm((f) => ({ ...f, changelog: e.target.value }))}
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="mandatory"
              checked={form.mandatory}
              onChange={(e) => setForm((f) => ({ ...f, mandatory: e.target.checked }))}
              className="h-4 w-4"
            />
            <Label htmlFor="mandatory">Mandatory update (force install)</Label>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Creating…' : 'Create Release'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function UpdatesPage() {
  const [flavorFilter, setFlavorFilter] = useState<string>('all');
  const { data, loading, error, refetch } = useReleases(
    'android',
    flavorFilter === 'all' ? undefined : flavorFilter,
  );
  const { data: devicesData } = useDevices({});
  const devices = devicesData?.items ?? [];
  const [pushStatus, setPushStatus] = useState<Record<string, string>>({});

  const releases = data?.releases ?? [];

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this release?')) return;
    try {
      const res = await fetch(`/api/v1/updates/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      refetch();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to delete');
    }
  };

  const handlePushToDevice = async (release: Release, deviceId: string) => {
    const key = `${release.id}:${deviceId}`;
    setPushStatus((s) => ({ ...s, [key]: 'pushing' }));
    try {
      await pushOtaUpdate(deviceId, release);
      setPushStatus((s) => ({ ...s, [key]: 'queued' }));
    } catch (e: unknown) {
      setPushStatus((s) => ({ ...s, [key]: 'error' }));
      alert(e instanceof Error ? e.message : 'Push failed');
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">OTA Updates</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage APK releases and push silent updates to devices
          </p>
        </div>
        <CreateReleaseDialog onCreated={refetch} />
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <Select value={flavorFilter} onValueChange={setFlavorFilter}>
          <SelectTrigger className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All flavors</SelectItem>
            <SelectItem value="enterprise">enterprise</SelectItem>
            <SelectItem value="dev">dev</SelectItem>
          </SelectContent>
        </Select>
        <Badge variant="outline">{releases.length} release{releases.length !== 1 ? 's' : ''}</Badge>
      </div>

      {/* Content */}
      {loading && <div className="text-muted-foreground">Loading releases…</div>}
      {error && <div className="text-destructive">Error: {error}</div>}
      {!loading && releases.length === 0 && (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          No releases yet. Create one with &ldquo;+ New Release&rdquo;.
        </div>
      )}

      <div className="grid gap-4">
        {releases.map((release) => (
          <div key={release.id} className="rounded-lg border p-4 flex flex-col gap-3">
            {/* Release header */}
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-base">v{release.version_name}</span>
                  <Badge variant="outline" className="text-xs">{release.flavor}</Badge>
                  <Badge variant="outline" className="text-xs">{release.platform}</Badge>
                  {release.mandatory && (
                    <Badge variant="destructive" className="text-xs">Mandatory</Badge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  Version code {release.version_code} · Released {new Date(release.created_at).toLocaleString()}
                </div>
                {release.changelog && (
                  <div className="text-sm mt-1 text-muted-foreground">{release.changelog}</div>
                )}
                <div className="text-xs text-muted-foreground mt-1 font-mono truncate max-w-[400px]">
                  SHA-256: {release.sha256 || '—'}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive shrink-0"
                onClick={() => handleDelete(release.id)}
              >
                Delete
              </Button>
            </div>

            {/* Push to device */}
            <div className="border-t pt-3">
              <div className="text-xs font-medium text-muted-foreground mb-2">Push OTA to device:</div>
              <div className="flex flex-wrap gap-2">
                {devices.slice(0, 8).map((device) => {
                  const key = `${release.id}:${device.id}`;
                  const st = pushStatus[key];
                  return (
                    <Button
                      key={device.id}
                      variant="outline"
                      size="sm"
                      className="text-xs h-7"
                      disabled={st === 'pushing'}
                      onClick={() => handlePushToDevice(release, device.id)}
                    >
                      {st === 'pushing' ? '⏳ ' : st === 'queued' ? '✓ ' : st === 'error' ? '✗ ' : ''}
                      {device.name}
                    </Button>
                  );
                })}
                {devices.length === 0 && (
                  <span className="text-xs text-muted-foreground">No enrolled devices</span>
                )}
                {devices.length > 8 && (
                  <span className="text-xs text-muted-foreground">+{devices.length - 8} more</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
