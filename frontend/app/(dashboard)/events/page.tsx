"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useDeviceEvents,
  useEventStats,
  useMarkEventProcessed,
  type DeviceEvent,
  type EventSeverity,
  type DeviceEventParams,
} from "@/lib/hooks/useDeviceEvents";
import { Button } from "@/src/shared/ui/button";
import { Card } from "@/components/ui/card";
import { PageFrame, PageHeading } from "@/src/shared/ui/page-layout";
import { useDebounce } from "@/lib/hooks/useDebounce";
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
  Zap,
  AlertTriangle,
  Info,
  Bug,
  AlertOctagon,
  CheckCircle2,
  BarChart3,
  Eye,
} from "lucide-react";

// ── Маппинг уровней серьёзности ──────────────────────────────────────

const SEVERITY_CONFIG: Record<
  EventSeverity,
  { label: string; color: string; icon: typeof Info }
> = {
  debug: {
    label: "Отладка",
    color: "bg-muted text-muted-foreground border-border",
    icon: Bug,
  },
  info: {
    label: "Информация",
    color: "bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/25",
    icon: Info,
  },
  warning: {
    label: "Предупреждение",
    color: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/25",
    icon: AlertTriangle,
  },
  error: {
    label: "Ошибка",
    color: "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/25",
    icon: AlertOctagon,
  },
  critical: {
    label: "Критическое",
    color: "bg-destructive/10 text-destructive border-destructive/25",
    icon: AlertOctagon,
  },
};

function SeverityBadge({ severity }: { severity: EventSeverity }) {
  const cfg = SEVERITY_CONFIG[severity] ?? SEVERITY_CONFIG.info;
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
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ── Главная страница ─────────────────────────────────────────────────

export default function EventsPage() {
  // Фильтры и пагинация
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 300);
  const [filterSeverity, setFilterSeverity] = useState("__all__");
  const [filterProcessed, setFilterProcessed] = useState("__all__");
  const [page, setPage] = useState(1);
  const [perPage] = useState(50);
  const [sortBy, setSortBy] = useState("occurred_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Диалоги
  const [detailEvent, setDetailEvent] = useState<DeviceEvent | null>(null);

  useEffect(() => setPage(1), [debouncedSearch]);

  // Параметры запроса
  const params: DeviceEventParams = useMemo(
    () => ({
      page,
      per_page: perPage,
      search: debouncedSearch || undefined,
      severity: filterSeverity !== "__all__" ? filterSeverity : undefined,
      processed:
        filterProcessed === "true"
          ? true
          : filterProcessed === "false"
            ? false
            : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
    }),
    [page, perPage, debouncedSearch, filterSeverity, filterProcessed, sortBy, sortDir],
  );

  // Данные
  const { data, isLoading, isFetching, isError, refetch } = useDeviceEvents(params);
  const { data: stats, isError: statsError } = useEventStats();
  const markProcessed = useMarkEventProcessed();

  const events = data?.items ?? [];
  const initialError = isError && !data;
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

  const hasFilters =
    filterSeverity !== "__all__" ||
    filterProcessed !== "__all__" ||
    debouncedSearch;

  const handleMarkProcessed = (event: DeviceEvent) => {
    markProcessed.mutate(event.id, {
      onSuccess: () => {
        setDetailEvent(null);
        toast.success("Событие отмечено как обработанное");
      },
      onError: () => toast.error("Не удалось обновить событие. Состояние сохранено."),
    });
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="События и диагностика"
        title="События устройств"
        description={`Журнал событий парка · ${total.toLocaleString("ru-RU")} записей`}
        actions={<Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} aria-hidden="true" />Обновить
        </Button>}
      />

      {/* Статистика */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
          <StatCard
            label="Всего"
            value={stats.total}
            icon={BarChart3}
            color="text-foreground"
          />
          <StatCard
            label="Не обработано"
            value={stats.unprocessed}
            icon={AlertTriangle}
            color="text-amber-400"
          />
          {Object.entries(SEVERITY_CONFIG).map(([key, cfg]) => (
            <StatCard
              key={key}
              label={cfg.label}
              value={stats.by_severity[key] ?? 0}
              icon={cfg.icon}
              color={
                key === "debug"
                  ? "text-gray-400"
                  : key === "info"
                    ? "text-blue-400"
                    : key === "warning"
                      ? "text-amber-400"
                      : key === "error"
                        ? "text-red-400"
                        : "text-rose-400"
              }
            />
          ))}
        </div>
      )}
      {statsError && <p role="status" className="text-sm text-muted-foreground">Сводная статистика временно недоступна; журнал продолжает загружаться.</p>}
      {isError && data && <p role="status" className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-sm text-warning">Не удалось обновить журнал. Показаны ранее загруженные события.</p>}

      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Поиск по типу, сообщению..."
            value={search}
            aria-label="Поиск событий"
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-9 text-xs font-mono bg-background border-border"
          />
        </div>

        <Select
          value={filterSeverity}
          onValueChange={(v) => {
            setFilterSeverity(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="h-9 w-[160px] text-xs font-mono">
            <SelectValue placeholder="Все уровни" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все уровни</SelectItem>
            {Object.entries(SEVERITY_CONFIG).map(([k, v]) => (
              <SelectItem key={k} value={k}>
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filterProcessed}
          onValueChange={(v) => {
            setFilterProcessed(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="h-9 w-[160px] text-xs font-mono">
            <SelectValue placeholder="Обработка" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Все</SelectItem>
            <SelectItem value="false">Не обработано</SelectItem>
            <SelectItem value="true">Обработано</SelectItem>
          </SelectContent>
        </Select>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => {
              setFilterSeverity("__all__");
              setFilterProcessed("__all__");
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
                  col="occurred_at"
                  label="Время"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <Th
                  col="event_type"
                  label="Тип"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <Th
                  col="severity"
                  label="Уровень"
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  Устройство
                </th>
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  Аккаунт
                </th>
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  Сообщение
                </th>
                <th className="px-3 py-2 text-center text-muted-foreground font-medium">
                  Обработано
                </th>
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
                      <AlertOctagon className="mx-auto mb-3 h-8 w-8 text-destructive" aria-hidden="true" />
                      <p className="font-medium">Не удалось загрузить события</p>
                      <p className="mt-1 text-sm text-muted-foreground">Проверьте доступ event:read и соединение с backend.</p>
                      <Button className="mt-4" variant="outline" onClick={() => void refetch()}>Повторить запрос</Button>
                    </div>
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-3 py-12 text-center text-muted-foreground"
                  >
                    <Zap className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    {hasFilters
                      ? "Ничего не найдено по фильтрам"
                      : "Нет событий"}
                  </td>
                </tr>
              ) : (
                events.map((evt) => (
                  <tr
                    key={evt.id}
                    className="border-b border-border/50 transition-colors hover:bg-muted/30"
                  >
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                      {formatDate(evt.occurred_at)}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">
                      {evt.event_type}
                    </td>
                    <td className="px-3 py-2.5">
                      <SeverityBadge severity={evt.severity} />
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {evt.device_name ?? (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {evt.account_login ? (
                        <span className="text-blue-400">
                          {evt.account_login}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground max-w-[300px] truncate">
                      {evt.message ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      {evt.processed ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 mx-auto" />
                      ) : (
                        <span className="w-2 h-2 bg-amber-400 rounded-full inline-block" />
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
                          onClick={() => setDetailEvent(evt)}
                          aria-label={`Открыть событие ${evt.event_type}`}
                          title="Подробности"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </Button>
                        {!evt.processed && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-emerald-400"
                            onClick={() => handleMarkProcessed(evt)}
                            disabled={markProcessed.isPending}
                            aria-label={`Отметить событие ${evt.event_type} обработанным`}
                            title="Отметить обработанным"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" />
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
              Стр. {page} из {pages} · {total} записей
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

      {/* Детали события */}
      <Dialog
        open={!!detailEvent}
        onOpenChange={(open) => !open && setDetailEvent(null)}
      >
        <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-primary" />
              Событие: {detailEvent?.event_type}
            </DialogTitle>
            <DialogDescription>Детали события, полученные из API Sphere.</DialogDescription>
          </DialogHeader>
          {detailEvent && (
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <DetailRow label="ID" value={detailEvent.id} />
                <DetailRow
                  label="Уровень"
                  value={
                    <SeverityBadge severity={detailEvent.severity} />
                  }
                />
                <DetailRow
                  label="Устройство"
                  value={detailEvent.device_name ?? detailEvent.device_id}
                />
                <DetailRow
                  label="Аккаунт"
                  value={detailEvent.account_login ?? "—"}
                />
                <DetailRow
                  label="Время"
                  value={new Date(detailEvent.occurred_at).toLocaleString(
                    "ru-RU",
                  )}
                />
                <DetailRow
                  label="Обработано"
                  value={detailEvent.processed ? "Да" : "Нет"}
                />
                {detailEvent.task_id && (
                  <DetailRow label="Task ID" value={detailEvent.task_id} />
                )}
                {detailEvent.pipeline_run_id && (
                  <DetailRow
                    label="Pipeline Run"
                    value={detailEvent.pipeline_run_id}
                  />
                )}
              </div>
              {detailEvent.message && (
                <div>
                  <span className="text-muted-foreground block mb-1">
                    Сообщение:
                  </span>
                  <div className="bg-muted/50 rounded p-2 text-foreground whitespace-pre-wrap">
                    {detailEvent.message}
                  </div>
                </div>
              )}
              {detailEvent.data &&
                Object.keys(detailEvent.data).length > 0 && (
                  <div>
                    <span className="text-muted-foreground block mb-1">
                      Данные:
                    </span>
                    <pre className="bg-muted/50 rounded p-2 text-foreground overflow-auto max-h-48">
                      {JSON.stringify(detailEvent.data, null, 2)}
                    </pre>
                  </div>
                )}
              {!detailEvent.processed && (
                <Button
                  size="sm"
                  className="w-full"
                  onClick={() => handleMarkProcessed(detailEvent)}
                  disabled={markProcessed.isPending}
                >
                  <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
                  Отметить обработанным
                </Button>
              )}
            </div>
          )}
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
}: {
  label: string;
  value: number;
  icon: typeof BarChart3;
  color: string;
}) {
  return (
    <div className="bg-card border border-border rounded-lg p-2.5 flex items-center gap-2">
      <Icon className={`w-4 h-4 ${color}`} />
      <div>
        <div className="text-lg font-bold text-foreground leading-tight">
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
