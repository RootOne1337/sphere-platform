"use client";

import { useState, useMemo, useCallback } from "react";
import {
  useGameAccounts,
  useAccountStats,
  useCreateGameAccount,
  useUpdateGameAccount,
  useDeleteGameAccount,
  useAssignGameAccount,
  useReleaseGameAccount,
  useImportGameAccounts,
  useServers,
  type GameAccount,
  type AccountStatus,
  type GameAccountParams,
} from "@/lib/hooks/useGameAccounts";
import { useDevices } from "@/lib/hooks/useDevices";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/src/shared/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Search,
  Plus,
  Upload,
  Trash2,
  Edit,
  Link,
  Unlink,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  RefreshCw,
  Eye,
  EyeOff,
  Filter,
  Gamepad2,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Ban,
  Shield,
  Phone,
  Archive,
  Power,
  BarChart3,
  Copy,
  Hash,
  User,
  Server,
  Key,
  Activity,
  Target,
  Coins,
  Scale,
  Calendar,
  Monitor,
  Zap,
} from "lucide-react";

// ── Маппинг статусов ─────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  AccountStatus,
  { label: string; color: string; icon: typeof CheckCircle2 }
> = {
  free: { label: "Свободен", color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30", icon: CheckCircle2 },
  in_use: { label: "В работе", color: "bg-blue-500/20 text-blue-400 border-blue-500/30", icon: Power },
  cooldown: { label: "Кулдаун", color: "bg-amber-500/20 text-amber-400 border-amber-500/30", icon: Clock },
  banned: { label: "Забанен", color: "bg-red-500/20 text-red-400 border-red-500/30", icon: Ban },
  captcha: { label: "Капча", color: "bg-orange-500/20 text-orange-400 border-orange-500/30", icon: Shield },
  phone_verify: { label: "Верификация", color: "bg-purple-500/20 text-purple-400 border-purple-500/30", icon: Phone },
  disabled: { label: "Отключён", color: "bg-gray-500/20 text-gray-400 border-gray-500/30", icon: AlertTriangle },
  archived: { label: "Архив", color: "bg-gray-600/20 text-gray-500 border-gray-600/30", icon: Archive },
  pending_registration: { label: "Ожидает рег.", color: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30", icon: Clock },
};

function StatusBadge({ status }: { status: AccountStatus }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.free;
  const Icon = cfg.icon;
  return (
    <Badge variant="outline" className={`${cfg.color} font-mono text-[10px] gap-1 px-2 py-0.5 border`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </Badge>
  );
}

/** Форматирование сервера с номером: #1 RED */
function formatServer(name: string | null, servers?: Array<{ id: number; name: string }>) {
  if (!name) return "—";
  const srv = servers?.find((s) => s.name === name);
  return srv ? `#${srv.id} ${srv.name}` : name;
}

/** Копирование в буфер обмена */
function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {});
}

// ── Главная страница ─────────────────────────────────────────────────────────

export default function AccountsPage() {
  // Фильтры и пагинация
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterGame, setFilterGame] = useState("__all__");
  const [filterStatus, setFilterStatus] = useState("__all__");
  const [filterServer, setFilterServer] = useState("__all__");
  const [page, setPage] = useState(1);
  const [perPage] = useState(50);
  const [sortBy, setSortBy] = useState("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Диалоги
  const [createOpen, setCreateOpen] = useState(false);
  const [editAccount, setEditAccount] = useState<GameAccount | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [assignAccount, setAssignAccount] = useState<GameAccount | null>(null);
  const [releaseAccount, setReleaseAccount] = useState<GameAccount | null>(null);
  const [deleteAccount, setDeleteAccount] = useState<GameAccount | null>(null);
  const [detailAccount, setDetailAccount] = useState<GameAccount | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  // Дебаунс поиска
  const handleSearchChange = useCallback(
    (val: string) => {
      setSearch(val);
      const timer = setTimeout(() => {
        setDebouncedSearch(val);
        setPage(1);
      }, 300);
      return () => clearTimeout(timer);
    },
    [],
  );

  // Параметры запроса
  const params: GameAccountParams = useMemo(
    () => ({
      page,
      per_page: perPage,
      search: debouncedSearch || undefined,
      game: filterGame !== "__all__" ? filterGame : undefined,
      status: filterStatus !== "__all__" ? filterStatus : undefined,
      server_name: filterServer !== "__all__" ? filterServer : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
    }),
    [page, perPage, debouncedSearch, filterGame, filterStatus, filterServer, sortBy, sortDir],
  );

  // Данные
  const { data, isLoading, refetch } = useGameAccounts(params);
  const { data: stats } = useAccountStats();
  const { data: devicesData } = useDevices({ page: 1, page_size: 5000 });
  const { data: serversData } = useServers();
  const serversList = serversData?.servers ?? [];

  // Мутации
  const createMut = useCreateGameAccount();
  const updateMut = useUpdateGameAccount();
  const deleteMut = useDeleteGameAccount();
  const assignMut = useAssignGameAccount();
  const releaseMut = useReleaseGameAccount();
  const importMut = useImportGameAccounts();

  const accounts = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;

  // Сортировка
  const handleSort = (col: string) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
    setPage(1);
  };

  const hasFilters = filterGame !== "__all__" || filterStatus !== "__all__" || filterServer !== "__all__" || debouncedSearch;

  return (
    <div className="p-4 md:p-6 space-y-4 font-mono">
      {/* ── Заголовок ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
            <Gamepad2 className="w-6 h-6 text-primary" />
            Game Accounts
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Управление игровыми аккаунтами · {total} записей
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="w-3.5 h-3.5 mr-1" />
            Обновить
          </Button>
          <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="w-3.5 h-3.5 mr-1" />
            Импорт
          </Button>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="w-3.5 h-3.5 mr-1" />
            Создать
          </Button>
        </div>
      </div>

      {/* ── Статистика ─────────────────────────────────────────────────── */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-9 gap-2">
          <StatCard label="Всего" value={stats.total} icon={BarChart3} color="text-foreground" />
          <StatCard label="Свободных" value={stats.free} icon={CheckCircle2} color="text-emerald-400" />
          <StatCard label="В работе" value={stats.in_use} icon={Power} color="text-blue-400" />
          <StatCard label="Кулдаун" value={stats.cooldown} icon={Clock} color="text-amber-400" />
          <StatCard label="Забанено" value={stats.banned} icon={Ban} color="text-red-400" />
          <StatCard label="Капча" value={stats.captcha} icon={Shield} color="text-orange-400" />
          <StatCard label="Верификация" value={stats.phone_verify} icon={Phone} color="text-purple-400" />
          <StatCard label="Ожидает рег." value={stats.pending_registration} icon={Clock} color="text-cyan-400" />
          <StatCard label="Прокачано" value={stats.leveled} icon={Target} color="text-green-400" />
        </div>
      )}

      {/* ── Фильтры ───────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Поиск по нику, логину..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-8 h-9 text-xs font-mono bg-background border-border"
          />
        </div>

        <Select value={filterGame} onValueChange={(v) => { setFilterGame(v); setPage(1); }}>
          <SelectTrigger className="h-9 w-[140px] text-xs font-mono">
            <SelectValue placeholder="Все игры" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все игры</SelectItem>
            {stats?.games.map((g) => (
              <SelectItem key={g} value={g}>{g}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filterStatus} onValueChange={(v) => { setFilterStatus(v); setPage(1); }}>
          <SelectTrigger className="h-9 w-[150px] text-xs font-mono">
            <SelectValue placeholder="Все статусы" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все статусы</SelectItem>
            {Object.entries(STATUS_CONFIG).map(([k, v]) => (
              <SelectItem key={k} value={k}>{v.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filterServer} onValueChange={(v) => { setFilterServer(v); setPage(1); }}>
          <SelectTrigger className="h-9 w-[170px] text-xs font-mono">
            <SelectValue placeholder="Все серверы" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все серверы</SelectItem>
            {serversList.map((s) => (
              <SelectItem key={s.id} value={s.name}>#{s.id} {s.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => {
              setFilterGame("__all__");
              setFilterStatus("__all__");
              setFilterServer("__all__");
              setSearch("");
              setDebouncedSearch("");
              setPage(1);
            }}
          >
            <Filter className="w-3 h-3 mr-1" />
            Сброс
          </Button>
        )}
      </div>

      {/* ── Таблица ────────────────────────────────────────────────────── */}
      <div className="border border-border rounded-lg overflow-hidden bg-card">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-muted/50 border-b border-border">
                <th className="px-2 py-2 text-left text-muted-foreground font-medium w-8">#</th>
                <Th col="game" label="Игра" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="nickname" label="Ник / Логин" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="server_name" label="Сервер" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">Пароль</th>
                <Th col="status" label="Статус" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">Причина</th>
                <Th col="gender" label="Пол" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">Устройство</th>
                <Th col="assigned_at" label="Назначен" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="level" label="LVL" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="experience" label="XP" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="balance_rub" label="₽ RUB" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="balance_bc" label="BC" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="lawfulness" label="Закон" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-muted-foreground font-medium whitespace-nowrap">VIP</th>
                <Th col="total_bans" label="Баны" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="total_sessions" label="Сессии" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="cooldown_until" label="Кулдаун до" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="registered_at" label="Дата рег." sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="registration_provider" label="Провайдер" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="created_at" label="Создан" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <Th col="updated_at" label="Обновлён" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Действия</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={24} className="px-3 py-12 text-center text-muted-foreground">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                    Загрузка...
                  </td>
                </tr>
              ) : accounts.length === 0 ? (
                <tr>
                  <td colSpan={24} className="px-3 py-12 text-center text-muted-foreground">
                    <Gamepad2 className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    {hasFilters ? "Ничего не найдено по фильтрам" : "Нет аккаунтов. Создайте первый!"}
                  </td>
                </tr>
              ) : (
                accounts.map((acc, idx) => (
                  <tr
                    key={acc.id}
                    className="border-b border-border/50 hover:bg-muted/30 transition-colors cursor-pointer"
                    onClick={() => setDetailAccount(acc)}
                  >
                    {/* # — порядковый номер */}
                    <td className="px-2 py-2 text-muted-foreground/50">{(page - 1) * perPage + idx + 1}</td>

                    {/* Игра */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded">{acc.game}</span>
                    </td>

                    {/* Ник (= логин) */}
                    <td className="px-3 py-2.5 font-medium text-foreground whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <User className="w-3 h-3 text-primary/60 shrink-0" />
                        <span>{acc.nickname || acc.login}</span>
                        {acc.login !== acc.nickname && acc.nickname && (
                          <span className="text-muted-foreground/40 text-[9px]">({acc.login})</span>
                        )}
                      </div>
                    </td>

                    {/* Сервер с номером */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {acc.server_name ? (
                        <span className="text-primary text-[11px]">
                          {formatServer(acc.server_name, serversList)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>

                    {/* Пароль с кнопкой копирования */}
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <PasswordCell password={acc.password} />
                    </td>

                    {/* Статус */}
                    <td className="px-3 py-2.5">
                      <StatusBadge status={acc.status} />
                    </td>

                    {/* Причина статуса */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.status_reason ? (
                        <span className="text-[10px] max-w-[120px] truncate block" title={acc.status_reason}>{acc.status_reason}</span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Пол */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.gender === "male" ? (
                        <span className="text-blue-400 text-[10px]">М</span>
                      ) : acc.gender === "female" ? (
                        <span className="text-pink-400 text-[10px]">Ж</span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Устройство */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {acc.device_name ? (
                        <span className="text-blue-400 flex items-center gap-1">
                          <Monitor className="w-3 h-3" />
                          {acc.device_name}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>

                    {/* Назначен (дата привязки к устройству) */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {acc.assigned_at ? (
                        <span className="text-[10px]">{new Date(acc.assigned_at).toLocaleString("ru-RU", {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}</span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Уровень / целевой */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.level != null ? (
                        <span className="whitespace-nowrap">
                          <span className="text-foreground font-medium">{acc.level}</span>
                          {acc.target_level != null && <span className="text-muted-foreground/60">/{acc.target_level}</span>}
                          {acc.is_leveled && <span className="ml-1 text-emerald-400 text-[9px]">✓</span>}
                        </span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Опыт */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.experience != null ? acc.experience.toLocaleString("ru-RU") : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Баланс ₽ */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.balance_rub != null ? (
                        <span className="text-amber-300">{acc.balance_rub.toLocaleString("ru-RU")}</span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* BC */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.balance_bc != null ? acc.balance_bc.toLocaleString("ru-RU") : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Законопослушность */}
                    <td className="px-3 py-2.5">
                      {acc.lawfulness != null ? (
                        <span className={acc.lawfulness >= 70 ? "text-emerald-400" : acc.lawfulness >= 40 ? "text-amber-400" : "text-red-400"}>
                          {acc.lawfulness}
                        </span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* VIP */}
                    <td className="px-3 py-2.5">
                      {acc.vip_type && acc.vip_type !== "none" ? (
                        <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-400">
                          {acc.vip_type.toUpperCase()}
                          {acc.vip_expires_at && (
                            <span className="ml-0.5 text-muted-foreground">→{new Date(acc.vip_expires_at).toLocaleDateString("ru-RU",{day:"2-digit",month:"2-digit"})}</span>
                          )}
                        </Badge>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Баны */}
                    <td className="px-3 py-2.5">
                      {acc.total_bans > 0 ? (
                        <span className="text-red-400 font-medium" title={acc.ban_reason ? `${acc.ban_reason} · ${acc.last_ban_at ? new Date(acc.last_ban_at).toLocaleDateString("ru-RU") : ""}` : undefined}>
                          {acc.total_bans}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/40">0</span>
                      )}
                    </td>

                    {/* Сессии */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.total_sessions > 0 ? (
                        <span title={acc.last_session_end ? `Последняя: ${new Date(acc.last_session_end).toLocaleString("ru-RU")}` : undefined}>
                          {acc.total_sessions}
                        </span>
                      ) : <span className="text-muted-foreground/40">0</span>}
                    </td>

                    {/* Кулдаун до */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {acc.cooldown_until ? (
                        <span className={new Date(acc.cooldown_until) > new Date() ? "text-amber-400 text-[10px]" : "text-muted-foreground/40 text-[10px] line-through"}>
                          {new Date(acc.cooldown_until).toLocaleString("ru-RU", {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}
                        </span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Дата регистрации */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {acc.registered_at ? new Date(acc.registered_at).toLocaleDateString("ru-RU") : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Провайдер регистрации */}
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {acc.registration_provider ? (
                        <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded">{acc.registration_provider}</span>
                      ) : <span className="text-muted-foreground/40">—</span>}
                    </td>

                    {/* Дата создания */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {new Date(acc.created_at).toLocaleDateString("ru-RU")}
                    </td>

                    {/* Дата обновления */}
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {new Date(acc.updated_at).toLocaleString("ru-RU", {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}
                    </td>

                    {/* Действия */}
                    <td className="px-3 py-2.5 text-right">
                      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setEditAccount(acc)} title="Редактировать">
                          <Edit className="w-3.5 h-3.5" />
                        </Button>
                        {acc.status === "free" && (
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-blue-400" onClick={() => setAssignAccount(acc)} title="Назначить">
                            <Link className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        {acc.status === "in_use" && (
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-amber-400" onClick={() => setReleaseAccount(acc)} title="Освободить">
                            <Unlink className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive" onClick={() => setDeleteAccount(acc)} title="Удалить">
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Пагинация */}
        {pages > 1 && (
          <div className="flex items-center justify-between px-3 py-2 border-t border-border bg-muted/30">
            <span className="text-xs text-muted-foreground">
              Стр. {page} из {pages} · {total} записей
            </span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-7" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft className="w-3 h-3" />
              </Button>
              <Button variant="outline" size="sm" className="h-7" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                <ChevronRight className="w-3 h-3" />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* ── Диалоги ──────────────────────────────────────────────────── */}

      <CreateAccountDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={(data) => { createMut.mutate(data, { onSuccess: () => setCreateOpen(false) }); }}
        isLoading={createMut.isPending}
        servers={serversList}
      />

      <EditAccountDialog
        account={editAccount}
        onClose={() => setEditAccount(null)}
        onSave={(data) => {
          if (editAccount) { updateMut.mutate({ id: editAccount.id, ...data }, { onSuccess: () => setEditAccount(null) }); }
        }}
        isLoading={updateMut.isPending}
        servers={serversList}
        devices={devicesData?.items ?? []}
      />

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImport={(data) => { importMut.mutate(data, { onSuccess: () => setImportOpen(false) }); }}
        result={importMut.data}
        isLoading={importMut.isPending}
      />

      <AssignDialog
        account={assignAccount}
        devices={devicesData?.items ?? []}
        onClose={() => setAssignAccount(null)}
        onAssign={(deviceId) => {
          if (assignAccount) { assignMut.mutate({ id: assignAccount.id, device_id: deviceId }, { onSuccess: () => setAssignAccount(null) }); }
        }}
        isLoading={assignMut.isPending}
      />

      <ReleaseDialog
        account={releaseAccount}
        onClose={() => setReleaseAccount(null)}
        onRelease={(cooldown) => {
          if (releaseAccount) { releaseMut.mutate({ id: releaseAccount.id, cooldown_minutes: cooldown }, { onSuccess: () => setReleaseAccount(null) }); }
        }}
        isLoading={releaseMut.isPending}
      />

      <DeleteDialog
        account={deleteAccount}
        onClose={() => setDeleteAccount(null)}
        onConfirm={() => {
          if (deleteAccount) { deleteMut.mutate(deleteAccount.id, { onSuccess: () => setDeleteAccount(null) }); }
        }}
        isLoading={deleteMut.isPending}
      />

      <DetailDialog
        account={detailAccount}
        onClose={() => { setDetailAccount(null); setShowPassword(false); }}
        showPassword={showPassword}
        onTogglePassword={() => setShowPassword(!showPassword)}
        servers={serversList}
      />
    </div>
  );
}

// ── Вспомогательные компоненты ───────────────────────────────────────────────

function StatCard({ label, value, icon: Icon, color }: { label: string; value: number; icon: typeof BarChart3; color: string }) {
  return (
    <div className="bg-card border border-border rounded-lg p-2.5 flex items-center gap-2">
      <Icon className={`w-4 h-4 ${color}`} />
      <div>
        <div className="text-lg font-bold text-foreground leading-tight">{value}</div>
        <div className="text-[10px] text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function Th({ col, label, sortBy, sortDir, onSort }: { col: string; label: string; sortBy: string; sortDir: string; onSort: (c: string) => void }) {
  return (
    <th
      className="px-3 py-2 text-left text-muted-foreground font-medium cursor-pointer hover:text-foreground select-none whitespace-nowrap"
      onClick={() => onSort(col)}
    >
      {label}
      {sortBy === col && (sortDir === "asc" ? <ChevronUp className="w-3 h-3 inline ml-0.5" /> : <ChevronDown className="w-3 h-3 inline ml-0.5" />)}
    </th>
  );
}

/** Ячейка пароля — скрытый по умолчанию, с копированием */
function PasswordCell({ password }: { password?: string }) {
  const [visible, setVisible] = useState(false);
  if (!password) return <span className="text-muted-foreground/40">—</span>;
  return (
    <div className="flex items-center gap-1">
      <span className="text-muted-foreground text-[11px] font-mono">
        {visible ? password : "••••••••"}
      </span>
      <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => setVisible(!visible)}>
        {visible ? <EyeOff className="w-2.5 h-2.5" /> : <Eye className="w-2.5 h-2.5" />}
      </Button>
      <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => copyToClipboard(password)} title="Копировать">
        <Copy className="w-2.5 h-2.5" />
      </Button>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Создание аккаунта
// ══════════════════════════════════════════════════════════════════════════════

function CreateAccountDialog({
  open,
  onClose,
  onCreate,
  isLoading,
  servers,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (data: { game: string; login: string; password: string; server_name?: string; nickname?: string; gender?: string; level?: number; target_level?: number; balance_rub?: number; balance_bc?: number; meta?: Record<string, unknown> }) => void;
  isLoading: boolean;
  servers: Array<{ id: number; name: string }>;
}) {
  const [game, setGame] = useState("com.br.top");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [serverName, setServerName] = useState("");
  const [nickname, setNickname] = useState("");
  const [gender, setGender] = useState("male");
  const [level, setLevel] = useState("");
  const [targetLevel, setTargetLevel] = useState("");
  const [balanceRub, setBalanceRub] = useState("");
  const [balanceBc, setBalanceBc] = useState("");
  const [lawfulness, setLawfulness] = useState("");

  const handleSubmit = () => {
    const data: {
      game: string; login: string; password: string;
      server_name?: string; nickname?: string; gender?: string;
      level?: number; target_level?: number;
      balance_rub?: number; balance_bc?: number;
    } = {
      game: game.trim(),
      login: login.trim(),
      password,
      server_name: serverName || undefined,
      nickname: nickname.trim() || login.trim() || undefined,
      gender: gender || undefined,
    };
    if (level) data.level = parseInt(level);
    if (targetLevel) data.target_level = parseInt(targetLevel);
    if (balanceRub) data.balance_rub = parseFloat(balanceRub);
    if (balanceBc) data.balance_bc = parseFloat(balanceBc);
    onCreate(data);
  };

  const handleClose = () => {
    setGame("com.br.top"); setLogin(""); setPassword(""); setServerName(""); setNickname("");
    setGender("male"); setLevel(""); setTargetLevel(""); setBalanceRub(""); setBalanceBc(""); setLawfulness("");
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[600px] bg-card border-border max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Plus className="w-5 h-5 text-primary" />
            Создать аккаунт
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            Добавить новый игровой аккаунт. Логин = Никнейм (формат: Имя_Фамилия).
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          {/* Строка 1: Игра + Пол */}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Gamepad2 className="w-3 h-3" /> Игра *</Label>
              <Input value={game} onChange={(e) => setGame(e.target.value)} placeholder="com.br.top" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><User className="w-3 h-3" /> Пол</Label>
              <Select value={gender} onValueChange={setGender}>
                <SelectTrigger className="text-xs font-mono"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="male">Мужской</SelectItem>
                  <SelectItem value="female">Женский</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Строка 2: Логин + Никнейм (синхронизированы) */}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><User className="w-3 h-3" /> Логин / Ник *</Label>
              <Input
                value={login}
                onChange={(e) => { setLogin(e.target.value); setNickname(e.target.value); }}
                placeholder="Ivan_Petrov"
                className="text-xs font-mono"
              />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Key className="w-3 h-3" /> Пароль *</Label>
              <Input type="text" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Авто-генерация если пусто" className="text-xs font-mono" />
            </div>
          </div>

          {/* Строка 3: Сервер */}
          <div className="grid gap-1.5">
            <Label className="text-xs font-mono flex items-center gap-1"><Server className="w-3 h-3" /> Сервер</Label>
            <Select value={serverName} onValueChange={setServerName}>
              <SelectTrigger className="text-xs font-mono"><SelectValue placeholder="Выберите сервер" /></SelectTrigger>
              <SelectContent>
                {servers.map((s) => (
                  <SelectItem key={s.id} value={s.name}>#{s.id} {s.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Строка 4: Уровни */}
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Activity className="w-3 h-3" /> Уровень</Label>
              <Input type="number" value={level} onChange={(e) => setLevel(e.target.value)} placeholder="0" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Target className="w-3 h-3" /> Целевой LVL</Label>
              <Input type="number" value={targetLevel} onChange={(e) => setTargetLevel(e.target.value)} placeholder="0" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Scale className="w-3 h-3" /> Закон (0-100)</Label>
              <Input type="number" value={lawfulness} onChange={(e) => setLawfulness(e.target.value)} placeholder="100" min={0} max={100} className="text-xs font-mono" />
            </div>
          </div>

          {/* Строка 5: Балансы */}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Coins className="w-3 h-3" /> Баланс ₽</Label>
              <Input type="number" value={balanceRub} onChange={(e) => setBalanceRub(e.target.value)} placeholder="0.00" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono flex items-center gap-1"><Coins className="w-3 h-3" /> Баланс BC</Label>
              <Input type="number" value={balanceBc} onChange={(e) => setBalanceBc(e.target.value)} placeholder="0.00" className="text-xs font-mono" />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={handleClose}>Отмена</Button>
          <Button size="sm" onClick={handleSubmit} disabled={!game.trim() || !login.trim() || !password || isLoading}>
            {isLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : <Plus className="w-3.5 h-3.5 mr-1" />}
            Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Редактирование — ПОЛНЫЙ набор настроек
// ══════════════════════════════════════════════════════════════════════════════

function EditAccountDialog({
  account,
  onClose,
  onSave,
  isLoading,
  servers,
  devices,
}: {
  account: GameAccount | null;
  onClose: () => void;
  onSave: (data: Record<string, unknown>) => void;
  isLoading: boolean;
  servers: Array<{ id: number; name: string }>;
  devices: Array<{ id: string; name: string; status: string }>;
}) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const [statusReason, setStatusReason] = useState("");
  const [serverName, setServerName] = useState("");
  const [nickname, setNickname] = useState("");
  const [gender, setGender] = useState("");
  const [level, setLevel] = useState("");
  const [targetLevel, setTargetLevel] = useState("");
  const [experience, setExperience] = useState("");
  const [balanceRub, setBalanceRub] = useState("");
  const [balanceBc, setBalanceBc] = useState("");
  const [vipType, setVipType] = useState("");
  const [lawfulness, setLawfulness] = useState("");
  const [meta, setMeta] = useState("");

  // Инициализация при открытии
  const prevId = useState<string | null>(null);
  if (account && prevId[0] !== account.id) {
    prevId[1](account.id);
    setLogin(account.login);
    setPassword("");
    setStatus(account.status);
    setStatusReason(account.status_reason ?? "");
    setServerName(account.server_name ?? "");
    setNickname(account.nickname ?? "");
    setGender(account.gender ?? "male");
    setLevel(account.level?.toString() ?? "");
    setTargetLevel(account.target_level?.toString() ?? "");
    setExperience(account.experience?.toString() ?? "");
    setBalanceRub(account.balance_rub?.toString() ?? "");
    setBalanceBc(account.balance_bc?.toString() ?? "");
    setVipType(account.vip_type ?? "none");
    setLawfulness(account.lawfulness?.toString() ?? "");
    setMeta(account.meta ? JSON.stringify(account.meta, null, 2) : "{}");
  }
  if (!account && prevId[0]) { prevId[1](null); }

  return (
    <Dialog open={!!account} onOpenChange={() => onClose()}>
      <DialogContent className="sm:max-w-[680px] bg-card border-border max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Edit className="w-5 h-5 text-primary" />
            Редактировать аккаунт
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {account?.game} · {account?.nickname || account?.login} · ID: {account?.id?.slice(0, 8)}...
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* ── Раздел: Основное ───────────────────────────────────────── */}
          <SectionLabel icon={User} label="Основное" />
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Логин / Ник</Label>
              <Input value={login} onChange={(e) => { setLogin(e.target.value); setNickname(e.target.value); }} className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Новый пароль</Label>
              <Input type="text" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Не менять если пусто" className="text-xs font-mono" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Статус</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger className="text-xs font-mono"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Пол</Label>
              <Select value={gender} onValueChange={setGender}>
                <SelectTrigger className="text-xs font-mono"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="male">Мужской</SelectItem>
                  <SelectItem value="female">Женский</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Причина статуса</Label>
              <Input value={statusReason} onChange={(e) => setStatusReason(e.target.value)} placeholder="—" className="text-xs font-mono" />
            </div>
          </div>

          {/* ── Раздел: Сервер + Устройство ────────────────────────────── */}
          <SectionLabel icon={Server} label="Сервер и привязка" />
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Сервер</Label>
              <Select value={serverName} onValueChange={setServerName}>
                <SelectTrigger className="text-xs font-mono"><SelectValue placeholder="Выберите сервер" /></SelectTrigger>
                <SelectContent>
                  {servers.map((s) => (
                    <SelectItem key={s.id} value={s.name}>#{s.id} {s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Устройство (привязка)</Label>
              <div className="text-xs font-mono text-muted-foreground bg-muted/30 border border-border rounded-md px-3 py-2">
                {account?.device_name ? (
                  <span className="text-blue-400 flex items-center gap-1"><Monitor className="w-3 h-3" />{account.device_name}</span>
                ) : (
                  <span>Не привязан — используйте кнопку «Назначить»</span>
                )}
              </div>
            </div>
          </div>

          {/* ── Раздел: Игровая статистика ──────────────────────────────── */}
          <SectionLabel icon={Activity} label="Игровая статистика" />
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Уровень</Label>
              <Input type="number" value={level} onChange={(e) => setLevel(e.target.value)} placeholder="0" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Целевой LVL</Label>
              <Input type="number" value={targetLevel} onChange={(e) => setTargetLevel(e.target.value)} placeholder="0" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Опыт (XP)</Label>
              <Input type="number" value={experience} onChange={(e) => setExperience(e.target.value)} placeholder="0" className="text-xs font-mono" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Баланс ₽</Label>
              <Input type="number" value={balanceRub} onChange={(e) => setBalanceRub(e.target.value)} placeholder="0.00" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Баланс BC</Label>
              <Input type="number" value={balanceBc} onChange={(e) => setBalanceBc(e.target.value)} placeholder="0.00" className="text-xs font-mono" />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">Законопослушность</Label>
              <Input type="number" value={lawfulness} onChange={(e) => setLawfulness(e.target.value)} min={0} max={100} placeholder="100" className="text-xs font-mono" />
            </div>
          </div>

          {/* ── Раздел: VIP ────────────────────────────────────────────── */}
          <SectionLabel icon={Zap} label="VIP" />
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">VIP тип</Label>
              <Select value={vipType} onValueChange={setVipType}>
                <SelectTrigger className="text-xs font-mono"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Нет</SelectItem>
                  <SelectItem value="silver">Silver</SelectItem>
                  <SelectItem value="gold">Gold</SelectItem>
                  <SelectItem value="platinum">Platinum</SelectItem>
                  <SelectItem value="diamond">Diamond</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs font-mono">VIP истекает</Label>
              <div className="text-xs font-mono text-muted-foreground bg-muted/30 border border-border rounded-md px-3 py-2">
                {account?.vip_expires_at ? new Date(account.vip_expires_at).toLocaleString("ru-RU") : "—"}
              </div>
            </div>
          </div>

          {/* ── Раздел: Метаданные ─────────────────────────────────────── */}
          <SectionLabel icon={Hash} label="Метаданные (JSON)" />
          <Textarea
            value={meta}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setMeta(e.target.value)}
            rows={3}
            className="text-xs font-mono bg-background"
            placeholder='{"emulator": "emu-1", "notes": "..."}'
          />
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" onClick={() => {
            const updates: Record<string, unknown> = {};
            if (login !== account?.login) { updates.login = login; updates.nickname = login; }
            if (password) updates.password = password;
            if (status !== account?.status) updates.status = status;
            if (statusReason !== (account?.status_reason ?? "")) updates.status_reason = statusReason || null;
            if (serverName !== (account?.server_name ?? "")) updates.server_name = serverName;
            if (nickname !== (account?.nickname ?? "")) updates.nickname = nickname;
            if (gender !== (account?.gender ?? "male")) updates.gender = gender;
            if (level && parseInt(level) !== account?.level) updates.level = parseInt(level);
            if (targetLevel && parseInt(targetLevel) !== account?.target_level) updates.target_level = parseInt(targetLevel);
            if (experience && parseInt(experience) !== account?.experience) updates.experience = parseInt(experience);
            if (balanceRub && parseFloat(balanceRub) !== account?.balance_rub) updates.balance_rub = parseFloat(balanceRub);
            if (balanceBc && parseFloat(balanceBc) !== account?.balance_bc) updates.balance_bc = parseFloat(balanceBc);
            if (vipType !== (account?.vip_type ?? "none")) updates.vip_type = vipType;
            if (lawfulness && parseInt(lawfulness) !== account?.lawfulness) updates.lawfulness = parseInt(lawfulness);
            try { const m = JSON.parse(meta); if (JSON.stringify(m) !== JSON.stringify(account?.meta ?? {})) updates.meta = m; } catch { /* невалидный JSON — не отправляем */ }
            onSave(updates);
          }} disabled={isLoading}>
            {isLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : null}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Заголовок секции в диалоге редактирования */
function SectionLabel({ icon: Icon, label }: { icon: typeof User; label: string }) {
  return (
    <div className="flex items-center gap-2 pt-2 pb-1 border-b border-border/30">
      <Icon className="w-3.5 h-3.5 text-primary" />
      <span className="text-xs font-mono font-semibold text-foreground uppercase tracking-wider">{label}</span>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Импорт
// ══════════════════════════════════════════════════════════════════════════════

function ImportDialog({
  open,
  onClose,
  onImport,
  result,
  isLoading,
}: {
  open: boolean;
  onClose: () => void;
  onImport: (data: { accounts: Array<{ game: string; login: string; password: string }> }) => void;
  result?: { created: number; skipped: number; errors: string[] } | null;
  isLoading: boolean;
}) {
  const [text, setText] = useState("");

  const handleImport = () => {
    const lines = text.split("\n").filter((l) => l.trim());
    const accounts = lines.map((line) => {
      const parts = line.split(/[;,\t]/).map((p) => p.trim());
      return { game: parts[0] || "", login: parts[1] || "", password: parts[2] || "" };
    }).filter((a) => a.game && a.login && a.password);
    if (accounts.length === 0) return;
    onImport({ accounts });
  };

  return (
    <Dialog open={open} onOpenChange={() => { setText(""); onClose(); }}>
      <DialogContent className="sm:max-w-[560px] bg-card border-border">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Upload className="w-5 h-5 text-primary" />
            Массовый импорт
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            Формат: игра;логин;пароль (по строке). Разделитель: ; , или Tab.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <textarea
            className="w-full h-48 p-3 text-xs font-mono bg-background border border-border rounded-md resize-none focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder={"com.br.top;Ivan_Petrov;myPassword123\ncom.br.top;Dmitriy_Ivanov;pass456"}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {result && (
            <div className="p-3 rounded border border-border bg-muted/50 text-xs font-mono space-y-1">
              <div className="text-emerald-400">Создано: {result.created}</div>
              <div className="text-amber-400">Пропущено (дубли): {result.skipped}</div>
              {result.errors.length > 0 && (
                <div className="text-red-400">Ошибки: {result.errors.join(", ")}</div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => { setText(""); onClose(); }}>Закрыть</Button>
          <Button size="sm" onClick={handleImport} disabled={!text.trim() || isLoading}>
            {isLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : <Upload className="w-3.5 h-3.5 mr-1" />}
            Импортировать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Назначение на устройство
// ══════════════════════════════════════════════════════════════════════════════

function AssignDialog({
  account,
  devices,
  onClose,
  onAssign,
  isLoading,
}: {
  account: GameAccount | null;
  devices: Array<{ id: string; name: string; status: string }>;
  onClose: () => void;
  onAssign: (deviceId: string) => void;
  isLoading: boolean;
}) {
  const [deviceId, setDeviceId] = useState("");

  return (
    <Dialog open={!!account} onOpenChange={() => { setDeviceId(""); onClose(); }}>
      <DialogContent className="sm:max-w-[420px] bg-card border-border">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Link className="w-5 h-5 text-blue-400" />
            Назначить на устройство
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {account?.nickname || account?.login} · {formatServer(account?.server_name ?? null)}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <Select value={deviceId} onValueChange={setDeviceId}>
            <SelectTrigger className="text-xs font-mono">
              <SelectValue placeholder="Выберите устройство (эмулятор)..." />
            </SelectTrigger>
            <SelectContent>
              {devices.map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  <span className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${d.status === "online" ? "bg-emerald-400" : d.status === "offline" ? "bg-red-400" : "bg-gray-400"}`} />
                    <Monitor className="w-3 h-3" />
                    {d.name}
                    <span className="text-muted-foreground/60 text-[9px] ml-1">({d.status})</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {devices.length === 0 && (
            <p className="text-xs text-muted-foreground">Нет зарегистрированных устройств</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => { setDeviceId(""); onClose(); }}>Отмена</Button>
          <Button size="sm" onClick={() => onAssign(deviceId)} disabled={!deviceId || isLoading}>
            {isLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : <Link className="w-3.5 h-3.5 mr-1" />}
            Назначить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Освобождение
// ══════════════════════════════════════════════════════════════════════════════

function ReleaseDialog({
  account,
  onClose,
  onRelease,
  isLoading,
}: {
  account: GameAccount | null;
  onClose: () => void;
  onRelease: (cooldownMinutes?: number) => void;
  isLoading: boolean;
}) {
  const [cooldown, setCooldown] = useState("");

  return (
    <Dialog open={!!account} onOpenChange={() => { setCooldown(""); onClose(); }}>
      <DialogContent className="sm:max-w-[420px] bg-card border-border">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Unlink className="w-5 h-5 text-amber-400" />
            Освободить аккаунт
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {account?.nickname || account?.login} · Устройство: {account?.device_name}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <div className="grid gap-1.5">
            <Label className="text-xs font-mono">Кулдаун (минуты)</Label>
            <Input
              type="number"
              value={cooldown}
              onChange={(e) => setCooldown(e.target.value)}
              placeholder="0 = без кулдауна"
              className="text-xs font-mono"
            />
            <p className="text-[10px] text-muted-foreground">
              Макс. 10080 мин. (7 дней). Пусто = немедленное освобождение.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => { setCooldown(""); onClose(); }}>Отмена</Button>
          <Button size="sm" onClick={() => onRelease(cooldown ? parseInt(cooldown) : undefined)} disabled={isLoading}>
            {isLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : <Unlink className="w-3.5 h-3.5 mr-1" />}
            Освободить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Удаление
// ══════════════════════════════════════════════════════════════════════════════

function DeleteDialog({
  account,
  onClose,
  onConfirm,
  isLoading,
}: {
  account: GameAccount | null;
  onClose: () => void;
  onConfirm: () => void;
  isLoading: boolean;
}) {
  return (
    <Dialog open={!!account} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[400px] bg-card border-border">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Trash2 className="w-5 h-5 text-destructive" />
            Удалить аккаунт
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            Аккаунт <strong>{account?.nickname || account?.login}</strong> будет удалён безвозвратно.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button variant="destructive" size="sm" onClick={onConfirm} disabled={isLoading}>
            {isLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : <Trash2 className="w-3.5 h-3.5 mr-1" />}
            Удалить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// ДИАЛОГ: Детальный просмотр (полная карточка аккаунта)
// ══════════════════════════════════════════════════════════════════════════════

function DetailDialog({
  account,
  onClose,
  showPassword,
  onTogglePassword,
  servers,
}: {
  account: GameAccount | null;
  onClose: () => void;
  showPassword: boolean;
  onTogglePassword: () => void;
  servers: Array<{ id: number; name: string }>;
}) {
  return (
    <Dialog open={!!account} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[600px] bg-card border-border max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-mono text-foreground flex items-center gap-2">
            <Gamepad2 className="w-5 h-5 text-primary" />
            {account?.nickname || account?.login}
          </DialogTitle>
          <DialogDescription asChild>
            <div className="font-mono text-xs flex items-center gap-2 text-muted-foreground">
              {account?.game}
              {account && <StatusBadge status={account.status} />}
              {account?.server_name && (
                <span className="text-primary">{formatServer(account.server_name, servers)}</span>
              )}
            </div>
          </DialogDescription>
        </DialogHeader>
        {account && (
          <div className="space-y-3 py-2 text-xs font-mono">
            {/* Основные данные */}
            <SectionLabel icon={User} label="Основные данные" />
            <div className="grid gap-1">
              <DetailRow label="ID" value={account.id} copyable />
              <DetailRow label="Логин" value={account.login} copyable />
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted-foreground">Пароль</span>
                <div className="flex items-center gap-1">
                  <span className="text-foreground">{showPassword ? account.password || "—" : "••••••••"}</span>
                  <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={onTogglePassword}>
                    {showPassword ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                  </Button>
                  {account.password && (
                    <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => copyToClipboard(account.password!)}>
                      <Copy className="w-3 h-3" />
                    </Button>
                  )}
                </div>
              </div>
              <DetailRow label="Статус" value={STATUS_CONFIG[account.status]?.label ?? account.status} />
              {account.status_reason && <DetailRow label="Причина" value={account.status_reason} />}
              <DetailRow label="Ник" value={account.nickname ?? "—"} />
              <DetailRow label="Пол" value={account.gender === "male" ? "Мужской" : account.gender === "female" ? "Женский" : "—"} />
              <DetailRow label="Сервер" value={formatServer(account.server_name, servers)} />
            </div>

            {/* Устройство */}
            <SectionLabel icon={Monitor} label="Привязка к устройству" />
            <div className="grid gap-1">
              <DetailRow label="Устройство" value={account.device_name ?? "Не привязан"} />
              {account.assigned_at && <DetailRow label="Назначен" value={new Date(account.assigned_at).toLocaleString("ru-RU")} />}
              {account.cooldown_until && <DetailRow label="Кулдаун до" value={new Date(account.cooldown_until).toLocaleString("ru-RU")} />}
            </div>

            {/* Игровая статистика */}
            <SectionLabel icon={Activity} label="Игровая статистика" />
            <div className="grid gap-1">
              <DetailRow label="Уровень" value={account.level != null ? `${account.level}${account.target_level != null ? ` / ${account.target_level}` : ""}${account.is_leveled ? " ✓ Прокачан" : ""}` : "—"} />
              <DetailRow label="Опыт (XP)" value={account.experience != null ? account.experience.toLocaleString("ru-RU") : "—"} />
              <DetailRow label="Баланс ₽" value={account.balance_rub != null ? `${account.balance_rub.toLocaleString("ru-RU")} ₽` : "—"} />
              <DetailRow label="Баланс BC" value={account.balance_bc != null ? account.balance_bc.toLocaleString("ru-RU") : "—"} />
              <DetailRow label="Законопослушность" value={account.lawfulness != null ? `${account.lawfulness}/100` : "—"} />
              {account.last_balance_update && <DetailRow label="Баланс обновлён" value={new Date(account.last_balance_update).toLocaleString("ru-RU")} />}
            </div>

            {/* VIP */}
            {account.vip_type && account.vip_type !== "none" && (
              <>
                <SectionLabel icon={Zap} label="VIP" />
                <div className="grid gap-1">
                  <DetailRow label="Тип" value={account.vip_type.toUpperCase()} />
                  {account.vip_expires_at && <DetailRow label="Истекает" value={new Date(account.vip_expires_at).toLocaleDateString("ru-RU")} />}
                </div>
              </>
            )}

            {/* Баны и сессии */}
            <SectionLabel icon={Ban} label="Баны и сессии" />
            <div className="grid gap-1">
              <DetailRow label="Всего банов" value={account.total_bans.toString()} />
              {account.last_ban_at && <DetailRow label="Последний бан" value={new Date(account.last_ban_at).toLocaleString("ru-RU")} />}
              {account.ban_reason && <DetailRow label="Причина бана" value={account.ban_reason} />}
              <DetailRow label="Всего сессий" value={account.total_sessions.toString()} />
              {account.last_session_end && <DetailRow label="Последняя сессия" value={new Date(account.last_session_end).toLocaleString("ru-RU")} />}
            </div>

            {/* Регистрация */}
            <SectionLabel icon={Calendar} label="Регистрация и даты" />
            <div className="grid gap-1">
              {account.registered_at && <DetailRow label="Дата рег. в игре" value={new Date(account.registered_at).toLocaleString("ru-RU")} />}
              {account.registration_provider && <DetailRow label="Провайдер" value={account.registration_provider} />}
              <DetailRow label="Создан в системе" value={new Date(account.created_at).toLocaleString("ru-RU")} />
              <DetailRow label="Обновлён" value={new Date(account.updated_at).toLocaleString("ru-RU")} />
            </div>

            {/* Meta */}
            {account.meta && Object.keys(account.meta).length > 0 && (
              <>
                <SectionLabel icon={Hash} label="Метаданные" />
                <pre className="text-[10px] p-2 bg-muted/30 rounded border border-border/30 overflow-x-auto">
                  {JSON.stringify(account.meta, null, 2)}
                </pre>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DetailRow({ label, value, copyable }: { label: string; value: string; copyable?: boolean }) {
  return (
    <div className="flex justify-between items-center py-1 border-b border-border/30">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1">
        <span className="text-foreground text-right max-w-[65%] truncate" title={value}>{value}</span>
        {copyable && (
          <Button variant="ghost" size="sm" className="h-4 w-4 p-0" onClick={() => copyToClipboard(value)}>
            <Copy className="w-2.5 h-2.5" />
          </Button>
        )}
      </div>
    </div>
  );
}
