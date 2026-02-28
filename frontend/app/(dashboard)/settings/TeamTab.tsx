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
            <Card className="border-border bg-muted rounded-sm">
                <CardContent className="p-10 text-center text-muted-foreground flex flex-col items-center gap-3">
                    <ShieldAlert className="w-8 h-8 text-destructive opacity-80" />
                    <p className="text-sm font-bold font-mono uppercase tracking-widest">Доступ запрещён</p>
                    <p className="text-xs">У вас нет административных прав для управления командой.</p>
                </CardContent>
            </Card>
        );
    }

    return (
        <Card className="border-border bg-muted rounded-sm">
            <CardHeader className="pb-3 border-b border-border">
                <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
                        <Users className="w-4 h-4 text-primary" />
                        Управление командой &amp; RBAC
                    </CardTitle>
                    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                        <DialogTrigger asChild>
                            <Button size="sm" className="font-mono text-xs uppercase tracking-wider h-8">
                                <UserPlus className="w-3.5 h-3.5 mr-1.5" /> Добавить
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader>
                                <DialogTitle className="font-mono text-sm uppercase tracking-widest">Новый участник</DialogTitle>
                            </DialogHeader>
                            <div className="space-y-4 pt-2">
                                <div className="space-y-1">
                                    <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">Email</Label>
                                    <Input
                                        type="email"
                                        placeholder="user@example.com"
                                        value={form.email}
                                        onChange={(e) => setForm({ ...form, email: e.target.value })}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">Пароль</Label>
                                    <Input
                                        type="password"
                                        placeholder="Temporary password"
                                        value={form.password}
                                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">Роль</Label>
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
                                    className="w-full mt-2 font-mono text-xs uppercase tracking-wider"
                                >
                                    {createUser.isPending ? 'Создание…' : 'Создать участника'}
                                </Button>
                            </div>
                        </DialogContent>
                    </Dialog>
                </div>
            </CardHeader>
            <CardContent className="pt-4">
                {isLoading ? (
                    <p className="text-xs text-muted-foreground font-mono py-4 text-center animate-pulse">Загрузка команды…</p>
                ) : !users || users.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground">
                        <Users className="w-8 h-8 mx-auto mb-2 opacity-30" />
                        <p className="text-[10px] font-mono uppercase tracking-widest font-bold">Пользователи не найдены</p>
                    </div>
                ) : (
                    <div className="space-y-1.5">
                        {users.map((u) => (
                            <div key={u.id} className="flex items-center justify-between p-3 rounded-sm bg-card border border-border hover:border-primary/30 transition-colors group">
                                <div className="flex flex-col gap-1 min-w-0 flex-1">
                                    <div className="flex items-center gap-2">
                                        <p className="font-medium text-sm truncate">{u.email}</p>
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
                                        className="h-8 border-border text-destructive hover:bg-destructive/10 hover:border-destructive/30"
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
