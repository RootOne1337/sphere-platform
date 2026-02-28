import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Users, UserPlus, ShieldAlert, PowerOff, ShieldCheck } from 'lucide-react';

interface UserDetail {
    id: string;
    email: string;
    role: string;
    is_active: boolean;
    created_at: string;
}

export function TeamTab() {
    const { user: currentUser } = useAuthStore();
    const qc = useQueryClient();
    const isAdmin = currentUser?.role === 'org_admin' || currentUser?.role === 'org_owner' || currentUser?.role === 'super_admin';

    const { data: users, isLoading } = useQuery({
        queryKey: ['users'],
        queryFn: async () => {
            const { data } = await api.get('/users?per_page=100');
            return data.items as UserDetail[];
        },
        enabled: isAdmin,
    });

    const [dialogOpen, setDialogOpen] = useState(false);
    const [form, setForm] = useState({ email: '', password: '', role: 'viewer' });

    const createUser = useMutation({
        mutationFn: async () => {
            await api.post('/users', form);
        },
        onSuccess: () => {
            setDialogOpen(false);
            setForm({ email: '', password: '', role: 'viewer' });
            qc.invalidateQueries({ queryKey: ['users'] });
        },
        onError: (err: any) => {
            alert(err.response?.data?.detail || err.message);
        }
    });

    const deactivateUser = useMutation({
        mutationFn: async (id: string) => {
            await api.patch(`/users/${id}/deactivate`);
        },
        onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
    });

    const updateRole = useMutation({
        mutationFn: async ({ id, role }: { id: string; role: string }) => {
            await api.put(`/users/${id}/role`, { role });
        },
        onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
        onError: (err: any) => {
            alert(err.response?.data?.detail || err.message);
        }
    });

    if (!isAdmin) {
        return (
            <Card>
                <CardContent className="p-10 text-center text-muted-foreground flex flex-col items-center gap-3">
                    <ShieldAlert className="w-8 h-8 text-destructive opacity-80" />
                    <p className="text-sm font-semibold">Access Denied</p>
                    <p className="text-xs">You do not have administrative permissions to manage the team.</p>
                </CardContent>
            </Card>
        );
    }

    return (
        <Card>
            <CardHeader>
                <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2">
                        <Users className="w-5 h-5" />
                        Team & RBAC Management
                    </CardTitle>
                    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                        <DialogTrigger asChild>
                            <Button size="sm" className="bg-primary text-primary-foreground">
                                <UserPlus className="w-4 h-4 mr-1.5" /> Invite User
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader>
                                <DialogTitle>Add New Team Member</DialogTitle>
                            </DialogHeader>
                            <div className="space-y-4 pt-2">
                                <div className="space-y-1">
                                    <Label>Email Address</Label>
                                    <Input
                                        type="email"
                                        placeholder="user@example.com"
                                        value={form.email}
                                        onChange={(e) => setForm({ ...form, email: e.target.value })}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label>Initial Password</Label>
                                    <Input
                                        type="password"
                                        placeholder="Temporary password"
                                        value={form.password}
                                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label>System Role</Label>
                                    <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="viewer">Viewer</SelectItem>
                                            <SelectItem value="operator">Operator</SelectItem>
                                            <SelectItem value="org_admin">Organization Admin</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <Button
                                    onClick={() => createUser.mutate()}
                                    disabled={createUser.isPending || !form.email || !form.password}
                                    className="w-full mt-2"
                                >
                                    {createUser.isPending ? 'Creating...' : 'Create Member'}
                                </Button>
                            </div>
                        </DialogContent>
                    </Dialog>
                </div>
            </CardHeader>
            <CardContent>
                {isLoading ? (
                    <p className="text-sm text-muted-foreground">Loading team members...</p>
                ) : !users || users.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-6">No users found.</p>
                ) : (
                    <div className="space-y-2">
                        {users.map((u) => (
                            <div key={u.id} className="flex items-center justify-between p-3 border border-[#333] rounded-sm bg-[#111]">
                                <div className="flex flex-col gap-1">
                                    <div className="flex items-center gap-2">
                                        <p className="font-semibold text-sm text-foreground">{u.email}</p>
                                        {u.id === currentUser?.id && <Badge variant="outline" className="text-[9px] h-4">YOU</Badge>}
                                        {!u.is_active && <Badge variant="destructive" className="text-[9px] h-4">INACTIVE</Badge>}
                                    </div>
                                    <p className="text-xs text-muted-foreground font-mono">
                                        ID: {u.id.split('-')[0]}••• · Joined {new Date(u.created_at).toLocaleDateString()}
                                    </p>
                                </div>
                                <div className="flex items-center gap-3">
                                    <Select
                                        value={u.role}
                                        disabled={updateRole.isPending || (!['super_admin', 'org_owner'].includes(currentUser?.role || ''))}
                                        onValueChange={(v) => updateRole.mutate({ id: u.id, role: v })}
                                    >
                                        <SelectTrigger className="h-8 w-[130px] text-xs">
                                            <ShieldCheck className="w-3 h-3 mr-1.5 text-primary" />
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="viewer">Viewer</SelectItem>
                                            <SelectItem value="operator">Operator</SelectItem>
                                            <SelectItem value="org_admin">Org Admin</SelectItem>
                                            <SelectItem value="org_owner">Org Owner</SelectItem>
                                        </SelectContent>
                                    </Select>

                                    <Button
                                        size="sm"
                                        variant="outline"
                                        className="h-8 border-[#333] text-destructive hover:bg-destructive/10 hover:border-destructive/30"
                                        disabled={u.id === currentUser?.id || !u.is_active || deactivateUser.isPending}
                                        onClick={() => {
                                            if (confirm(`Deactivate ${u.email}?`)) {
                                                deactivateUser.mutate(u.id);
                                            }
                                        }}
                                        title={u.id === currentUser?.id ? "Cannot deactivate yourself" : "Deactivate member"}
                                    >
                                        <PowerOff className="w-3 h-3 mr-1.5" /> Deactivate
                                    </Button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
