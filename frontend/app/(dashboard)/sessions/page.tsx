"use client";

import { useMemo, useState } from "react";
import {
  useAccountSessions,
  useSessionStats,
  useEndSession,
  type AccountSession,
  type SessionEndReason,
  type AccountSessionParams,
} from "@/lib/hooks/useAccountSessions";
import { Button } from "@/src/shared/ui/button";
import { Card } from "@/components/ui/card";
import { PageFrame, PageHeading } from "@/src/shared/ui/page-layout";
import { toast } from "sonner";
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
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  RefreshCw,
  Filter,
  History,
  Play,
  Square,
  CheckCircle2,
  Ban,
  Shield,
  AlertTriangle,
  RotateCcw,
  Clock,
  Wifi,
  Hand,
  BarChart3,
  Eye,
  Timer,
  Layers,
} from "lucide-react";

// ── Маппинг причин завершения ────────────────────────────────────────

const END_REASON_CONFIG: Record<
  SessionEndReason,
  { label: string; color: string; icon: typeof CheckCircle2 }
> = {
  completed: {
    label: "Завершена",
    color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    icon: CheckCircle2,
  },
  banned: {
    label: "Бан",
    color: "bg-red-500/20 text-red-400 border-red-500/30",
    icon: Ban,
  },
  captcha: {
    label: "Капча",
    color: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    icon: Shield,
  },
  error: {
    label: "Ошибка",
    color: "bg-red-500/20 text-red-400 border-red-500/30",
    icon: AlertTriangle,
  },
  manual: {
    label: "Вручную",
    color: "bg-gray-500/20 text-gray-400 border-gray-500/30",
    icon: Hand,
  },
  rotation: {
    label: "Ротация",
    color: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    icon: RotateCcw,
  },
  timeout: {
    label: "Таймаут",
    color: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    icon: Clock,
  },
  device_offline: {
    label: "Девайс оффлайн",
    color: "bg-gray-600/20 text-gray-500 border-gray-600/30",
    icon: Wifi,
  },
};

function EndReasonBadge({ reason }: { reason: SessionEndReason | null }) {
  if (!reason) {
    return (
      <Badge
        variant="outline"
        className="bg-blue-500/20 text-blue-400 border-blue-500/30 font-mono text-[10px] gap-1 px-2 py-0.5 border"
      >
        <Play className="w-3 h-3" />
        Активна
      </Badge>
    );
  }
  const cfg = END_REASON_CONFIG[reason] ?? END_REASON_CONFIG.error;
  const Icon = cfg.icon;
  return (
    <Badge
      variant="outline"
      className={`${cfg.color} font-mono text-[10px] gap-1 px-2 py-0.5 border`}
    >
      <Icon className="w-3 h-3" />
      {cfg.label}
    </Badge>
  );
}

// ── Вспомогательные ──────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}с`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}м ${s}с`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}ч ${m}м`;
}

// ── Главная страница ─────────────────────────────────────────────────

export default function SessionsPage() {
  // Фильтры и пагинация
  const [search, setSearch] = useState("");
  const [filterReason, setFilterReason] = useState("__all__");
  const [filterActive, setFilterActive] = useState("__all__");
  const [page, setPage] = useState(1);
  const [perPage] = useState(50);
  const [sortBy, setSortBy] = useState("started_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Диалоги
  const [detailSession, setDetailSession] = useState<AccountSession | null>(
    null,
  );
  const [sessionToEnd, setSessionToEnd] = useState<AccountSession | null>(null);

  // Параметры запроса
  const params: AccountSessionParams = useMemo(
    () => ({
      page,
      per_page: perPage,
      end_reason: filterReason !== "__all__" ? filterReason : undefined,
      active_only: filterActive === "active" ? true : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
    }),
    [page, perPage, filterReason, filterActive, sortBy, sortDir],
  );

  // Данные
  const { data, isLoading, isFetching, isError, refetch } = useAccountSessions(params);
  const { data: stats, isError: statsError } = useSessionStats();
  const endSession = useEndSession();

  const sessions = useMemo(() => data?.items ?? [], [data?.items]);
  const filteredSessions = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("ru-RU");
    if (!query) return sessions;
    return sessions.filter((session) => [
      session.account_login,
      session.account_game,
      session.device_name,
      session.device_id,
      session.end_reason,
      session.error_message,
      session.task_id,
      session.pipeline_run_id,
    ].some((value) => value?.toLocaleLowerCase("ru-RU").includes(query)));
  }, [sessions, search]);
  const initialError = isError && !data;
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;

  const handleSort = (col: string) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
    setPage(1);
  };

  const hasFilters =
    filterReason !== "__all__" ||
    filterActive !== "__all__" ||
    search.trim();

  const confirmEndSession = () => {
    if (!sessionToEnd) return;
    endSession.mutate(
      { id: sessionToEnd.id, end_reason: "manual" },
      {
        onSuccess: () => {
          setSessionToEnd(null);
          setDetailSession(null);
          toast.success("Сессия завершена");
        },
        onError: () => toast.error("Не удалось завершить сессию. Она остаётся активной."),
      },
    );
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="История и контроль"
        title="Сессии аккаунтов"
        description={`${total.toLocaleString("ru-RU")} записей · поиск ограничен загруженной страницей`}
        actions={<Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} aria-hidden="true" />Обновить
        </Button>}
      />

      {/* Статистика */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          <StatCard
            label="Всего сессий"
            value={stats.total_sessions}
            icon={BarChart3}
            color="text-foreground"
          />
          <StatCard
            label="Активных"
            value={stats.active_sessions}
            icon={Play}
            color="text-blue-400"
          />
          <StatCard
            label="Ср. длительность"
            value={
              stats.avg_duration_seconds != null
                ? formatDuration(Math.round(stats.avg_duration_seconds))
                : "—"
            }
            icon={Timer}
            color="text-amber-400"
            isText
          />
          <StatCard
            label="Нод выполнено"
            value={stats.total_nodes_executed}
            icon={Layers}
            color="text-emerald-400"
          />
          <StatCard
            label="Ошибок"
            value={stats.total_errors}
            icon={AlertTriangle}
            color="text-red-400"
          />
          <StatCard
            label="Завершено OK"
            value={stats.by_end_reason?.completed ?? 0}
            icon={CheckCircle2}
            color="text-emerald-400"
          />
        </div>
      )}
      {statsError && <p role="status" className="text-sm text-muted-foreground">Сводная статистика сессий временно недоступна.</p>}
      {isError && data && <p role="status" className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-sm text-warning">Не удалось обновить сессии. Показаны последние загруженные записи.</p>}

      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Поиск по аккаунту или устройству на странице"
            value={search}
            aria-label="Поиск сессий на текущей странице"
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="pl-8 h-9 text-xs font-mono bg-background border-border"
          />
        </div>

        <Select
          value={filterActive}
          onValueChange={(v) => {
            setFilterActive(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="h-9 w-[160px] text-xs font-mono">
            <SelectValue placeholder="Все сессии" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все сессии</SelectItem>
            <SelectItem value="active">Только активные</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={filterReason}
          onValueChange={(v) => {
            setFilterReason(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="h-9 w-[170px] text-xs font-mono">
            <SelectValue placeholder="Причина завершения" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все причины</SelectItem>
            {Object.entries(END_REASON_CONFIG).map(([k, v]) => (
              <SelectItem key={k} value={k}>
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => {
              setFilterReason("__all__");
              setFilterActive("__all__");
              setSearch("");
              setPage(1);
            }}
          >
            <Filter className="w-3 h-3 mr-1" />
            Сброс
          </Button>
        )}
      </div>

      {/* Таблица */}
      <Card className="overflow-hidden shadow-soft">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-muted/50 border-b border-border">
                <Th
                  col="started_at"
                  label="Начало"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  Аккаунт
                </th>
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  Устройство
                </th>
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  Статус
                </th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">
                  Длительность
                </th>
                <Th
                  col="nodes_executed"
                  label="Ноды"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <Th
                  col="errors_count"
                  label="Ошибки"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">
                  Действия
                </th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-3 py-12 text-center text-muted-foreground"
                  >
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                    Загрузка...
                  </td>
                </tr>
              ) : initialError ? (
                <tr>
                  <td colSpan={8} className="px-5 py-16 text-center" role="alert">
                    <div className="mx-auto max-w-md">
                      <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-destructive" aria-hidden="true" />
                      <p className="font-medium">Не удалось загрузить сессии</p>
                      <p className="mt-1 text-sm text-muted-foreground">Проверьте доступ session:read и соединение с backend.</p>
                      <Button className="mt-4" variant="outline" onClick={() => void refetch()}>Повторить запрос</Button>
                    </div>
                  </td>
                </tr>
              ) : filteredSessions.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-3 py-12 text-center text-muted-foreground"
                  >
                    <History className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    {hasFilters
                      ? "На этой странице нет совпадений"
                      : "Нет сессий"}
                  </td>
                </tr>
              ) : (
                filteredSessions.map((ses) => (
                  <tr
                    key={ses.id}
                    className="border-b border-border/50 hover:bg-muted/30 transition-colors cursor-pointer"
                    onClick={() => setDetailSession(ses)}
                  >
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {formatDate(ses.started_at)}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">
                      {ses.account_login ?? (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                      {ses.account_game && (
                        <span className="text-muted-foreground ml-1 text-[10px]">
                          ({ses.account_game})
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {ses.device_name ?? (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <EndReasonBadge reason={ses.end_reason} />
                    </td>
                    <td className="px-3 py-2.5 text-right text-muted-foreground font-medium tabular-nums">
                      {formatDuration(ses.duration_seconds)}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground tabular-nums">
                      {ses.nodes_executed}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums">
                      {ses.errors_count > 0 ? (
                        <span className="text-red-400 font-medium">
                          {ses.errors_count}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/50">0</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <div
                        className="flex justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                          onClick={() => setDetailSession(ses)}
                          aria-label={`Открыть сессию ${ses.account_login ?? ses.id}`}
                          title="Подробности"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </Button>
                        {!ses.ended_at && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-red-400"
                            onClick={() => setSessionToEnd(ses)}
                            disabled={endSession.isPending}
                            aria-label={`Завершить сессию ${ses.account_login ?? ses.id}`}
                            title="Завершить сессию"
                          >
                            <Square className="w-3.5 h-3.5" />
                          </Button>
                        )}
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
              На странице {filteredSessions.length} из {sessions.length} · стр. {page} из {pages} · всего {total}
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                aria-label="Предыдущая страница"
              >
                <ChevronLeft className="w-3 h-3" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={page >= pages}
                onClick={() => setPage(page + 1)}
                aria-label="Следующая страница"
              >
                <ChevronRight className="w-3 h-3" />
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Детали сессии */}
      <Dialog
        open={!!detailSession}
        onOpenChange={(open) => !open && setDetailSession(null)}
      >
        <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <History className="w-5 h-5 text-primary" />
              Сессия: {detailSession?.account_login ?? "—"}
            </DialogTitle>
            <DialogDescription>История и фактическое состояние сессии из API Sphere.</DialogDescription>
          </DialogHeader>
          {detailSession && (
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <DetailRow label="ID" value={detailSession.id} />
                <DetailRow
                  label="Статус"
                  value={
                    <EndReasonBadge reason={detailSession.end_reason} />
                  }
                />
                <DetailRow
                  label="Аккаунт"
                  value={detailSession.account_login ?? "—"}
                />
                <DetailRow
                  label="Устройство"
                  value={
                    detailSession.device_name ?? detailSession.device_id
                  }
                />
                <DetailRow
                  label="Начало"
                  value={new Date(detailSession.started_at).toLocaleString(
                    "ru-RU",
                  )}
                />
                <DetailRow
                  label="Конец"
                  value={
                    detailSession.ended_at
                      ? new Date(detailSession.ended_at).toLocaleString(
                          "ru-RU",
                        )
                      : "Ещё идёт"
                  }
                />
                <DetailRow
                  label="Длительность"
                  value={formatDuration(detailSession.duration_seconds)}
                />
                <DetailRow
                  label="Ноды"
                  value={String(detailSession.nodes_executed)}
                />
                <DetailRow
                  label="Ошибки"
                  value={String(detailSession.errors_count)}
                />
                {detailSession.level_before != null && (
                  <DetailRow
                    label="Уровень"
                    value={`${detailSession.level_before} → ${detailSession.level_after ?? "?"}`}
                  />
                )}
                {detailSession.balance_before != null && (
                  <DetailRow
                    label="Баланс"
                    value={`${detailSession.balance_before.toLocaleString()} → ${detailSession.balance_after?.toLocaleString() ?? "?"}`}
                  />
                )}
                {detailSession.task_id && (
                  <DetailRow
                    label="Task ID"
                    value={detailSession.task_id}
                  />
                )}
                {detailSession.pipeline_run_id && (
                  <DetailRow
                    label="Pipeline Run"
                    value={detailSession.pipeline_run_id}
                  />
                )}
              </div>
              {detailSession.error_message && (
                <div>
                  <span className="text-muted-foreground block mb-1">
                    Ошибка:
                  </span>
                  <div className="bg-red-500/10 border border-red-500/20 rounded p-2 text-red-400 whitespace-pre-wrap">
                    {detailSession.error_message}
                  </div>
                </div>
              )}
              {detailSession.meta &&
                Object.keys(detailSession.meta).length > 0 && (
                  <div>
                    <span className="text-muted-foreground block mb-1">
                      Метаданные:
                    </span>
                    <pre className="bg-muted/50 rounded p-2 text-foreground overflow-auto max-h-48">
                      {JSON.stringify(detailSession.meta, null, 2)}
                    </pre>
                  </div>
                )}
              {!detailSession.ended_at && (
                <Button
                  size="sm"
                  variant="destructive"
                  className="w-full"
                  onClick={() => setSessionToEnd(detailSession)}
                  disabled={endSession.isPending}
                >
                  <Square className="w-3.5 h-3.5 mr-1" />
                  Завершить сессию вручную
                </Button>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!sessionToEnd} onOpenChange={(open) => { if (!open && !endSession.isPending) setSessionToEnd(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Завершить активную сессию?</DialogTitle>
            <DialogDescription>Текущая сессия аккаунта будет закрыта с причиной «Вручную». Продолжить?</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setSessionToEnd(null)} disabled={endSession.isPending}>Отмена</Button>
            <Button variant="destructive" onClick={confirmEndSession} disabled={endSession.isPending}>
              {endSession.isPending ? "Завершаем…" : "Завершить сессию"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </PageFrame>
  );
}

// ── Вспомогательные компоненты ───────────────────────────────────────

function StatCard({
  label,
  value,
  icon: Icon,
  color,
  isText = false,
}: {
  label: string;
  value: number | string;
  icon: typeof BarChart3;
  color: string;
  isText?: boolean;
}) {
  return (
    <div className="bg-card border border-border rounded-lg p-2.5 flex items-center gap-2">
      <Icon className={`w-4 h-4 ${color}`} />
      <div>
        <div
          className={`${isText ? "text-sm" : "text-lg"} font-bold text-foreground leading-tight`}
        >
          {value}
        </div>
        <div className="text-[10px] text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function Th({
  col,
  label,
  sortBy,
  sortDir,
  onSort,
}: {
  col: string;
  label: string;
  sortBy: string;
  sortDir: string;
  onSort: (c: string) => void;
}) {
  return (
    <th
      className="px-3 py-2 text-left text-muted-foreground font-medium cursor-pointer hover:text-foreground select-none"
      onClick={() => onSort(col)}
    >
      {label}
      {sortBy === col &&
        (sortDir === "asc" ? (
          <ChevronUp className="w-3 h-3 inline ml-0.5" />
        ) : (
          <ChevronDown className="w-3 h-3 inline ml-0.5" />
        ))}
    </th>
  );
}

function DetailRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <span className="text-muted-foreground">{label}:</span>
      <div className="text-foreground mt-0.5">{value}</div>
    </div>
  );
}
