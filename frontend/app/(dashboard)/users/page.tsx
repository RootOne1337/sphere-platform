'use client';
import { useState } from 'react';
import { useUsers, useCreateUser, useUpdateRole, useDeactivateUser } from '@/lib/hooks/useUsers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Plus } from 'lucide-react';

const ROLES = ['viewer', 'script_runner', 'device_manager', 'org_admin', 'org_owner'] as const;

export default function UsersPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useUsers(page);
  const createUser = useCreateUser();
  const updateRole = useUpdateRole();
  const deactivateUser = useDeactivateUser();

  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('viewer');
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleCreate = async () => {
    await createUser.mutateAsync({ email: newEmail, password: newPassword, role: newRole });
    setNewEmail('');
    setNewPassword('');
    setNewRole('viewer');
    setDialogOpen(false);
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Users</h1>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              Add User
            </Button>
          </DialogTrigger>
          <DialogContent aria-describedby={undefined}>
            <DialogHeader>
              <DialogTitle>Create User</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-2">
              <div className="space-y-1">
                <Label>Email</Label>
                <Input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Password</Label>
                <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>Role</Label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="w-full rounded border bg-background px-3 py-2 text-sm"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <Button onClick={handleCreate} disabled={createUser.isPending || !newEmail || !newPassword} className="w-full">
                {createUser.isPending ? 'Creating…' : 'Create'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <>
          <div className="rounded border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="p-3">Email</th>
                  <th className="p-3">Role</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">MFA</th>
                  <th className="p-3">Last Login</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((user) => (
                  <tr key={user.id} className="border-b hover:bg-accent/50">
                    <td className="p-3">{user.email}</td>
                    <td className="p-3">
                      <select
                        value={user.role}
                        onChange={(e) => updateRole.mutate({ userId: user.id, role: e.target.value })}
                        className="rounded border bg-background px-2 py-1 text-xs"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                    <td className="p-3">
                      <Badge variant={user.is_active ? 'default' : 'destructive'}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="p-3">
                      {user.mfa_enabled ? (
                        <Badge variant="outline" className="text-green-400 border-green-600">On</Badge>
                      ) : (
                        <Badge variant="outline" className="text-gray-400">Off</Badge>
                      )}
                    </td>
                    <td className="p-3 text-xs text-muted-foreground">
                      {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : '—'}
                    </td>
                    <td className="p-3">
                      {user.is_active && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => deactivateUser.mutate(user.id)}
                          disabled={deactivateUser.isPending}
                        >
                          Deactivate
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data && data.pages > 1 && (
            <div className="flex items-center gap-2 justify-center">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Prev
              </Button>
              <span className="text-sm text-muted-foreground">{page} / {data.pages}</span>
              <Button size="sm" variant="outline" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
