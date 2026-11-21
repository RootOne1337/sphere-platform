"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { Flag, LocateFixed, MapPin, Navigation, X } from "lucide-react";
import { WorldDestinationMap } from "./WorldDestinationMap";
import styles from "./worldConsole.module.css";
import { Button } from "@/components/ui/button";
import type { TeachingInput } from "./teachingContacts";
import type { VehicleInputLease } from "./vehiclePilot";
import {
  probeWorldPosition,
  runWorldTrip,
  worldRequest,
  type Decision,
  type WorldInfo,
  type XYZ,
} from "./worldDestination";

import { WorldItinerary, useWorldItinerary, letter } from "./WorldItinerary";

const searchPhases: Record<string, string> = {
  collecting_views: "Собираем ракурсы",
  global_search: "Ищем место по всей карте",
  rendering_candidates: "Сверяем выбранные улицы",
  local_search: "Уточняем район",
  verifying_geometry: "Проверяем положение по 3D-карте",
  tracking: "Сверяем свежий кадр",
  no_verified_position: "Положение пока не подтверждено",
  search_error: "Сбой поиска по карте",
};

const reasons: Record<string, string> = {
  ambiguous_position: "Кадры дают разные положения. Нужен другой ракурс.",
  waypoint_reached: "Промежуточная точка достигнута",
  position_timeout: "Время поиска положения истекло",
  no_motion:
    "Поездка остановлена. Газ был запрошен, но скутер не сдвинулся. Проверьте топливо и калибровку педали.",
  following: "Движение по маршруту",
  confirming_position: "Подтверждаем положение по следующему кадру",
  position_unknown: "Ищем ориентиры в кадре",
  road_level_unknown: "Под скутером не подтверждена проезжая дорога",
  no_road_path: "До цели нет связной дороги",
  endpoint_off_road: "Конец пути выходит за проезжую часть",
  outside_visual_coverage: "Путь выходит из зоны визуальных ориентиров",
  outside_path: "Уточняем положение на дороге",
  turnaround_required: "Перед началом движения разверните скутер по маршруту",
  stopping: "Остановка у метки",
  arrived: "Прибытие подтверждено",
  frame_stale: "Кадр устарел",
  input_closed: "Канал управления закрыт",
  stream_stopped: "Поток остановлен",
  stream_geometry_or_clock: "Нужен свежий горизонтальный кадр 16:9",
  unreachable_goal: "Метка вне проезжей части",
  session_active: "Другой сеанс уже использует карту",
};
function problem(e: unknown) {
  const msg = e instanceof Error ? e.message : "";
  return (
    reasons[msg] ??
    (msg === "Failed to fetch"
      ? "Нет связи с локальной службой карты"
      : msg || "Ошибка связи с картой")
  );
}
export function WorldDestinationPilot({
  video,
  ready,
  connected,
  inputIssue,
  openInput,
}: {
  video: RefObject<HTMLVideoElement | null>;
  ready: boolean;
  connected: boolean;
  inputIssue: string | null;
  openInput: (
    signal: AbortSignal,
    journal: (event: TeachingInput) => void,
  ) => Promise<VehicleInputLease>;
}) {
  const [probing, setProbing] = useState(false),
    [probeMessage, setProbeMessage] = useState("");
  const [observation, setObservation] = useState<XYZ | null>(null);
  const probe = useRef<AbortController | null>(null);
  const [info, setInfo] = useState<WorldInfo | null>(null);
  const [suggestion, setSuggestion] = useState<{
    point: [number, number];
    distance: number;
  } | null>(null);
  const [covered, setCovered] = useState<number[]>([]);
  const [multiple, setMultiple] = useState(false);
  const [acquireMinutes, setAcquireMinutes] = useState(3);
  const itinerary = useWorldItinerary(info?.mapRevision);
  const [point, setPoint] = useState<[number, number] | null>(null),
    [levels, setLevels] = useState<number[]>([]),
    [level, setLevel] = useState<number | null>(null);
  const [status, setStatus] = useState("Загрузка карты"),
    [active, setActive] = useState(false),
    [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Decision | null>(null),
    [age, setAge] = useState<number | null>(null);
  const choice = useRef<AbortController | null>(null),
    run = useRef<AbortController | null>(null),
    mounted = useRef(false);
  const driving = useRef(false);
  const opening = useRef(openInput);
  opening.current = openInput;
  const stop = useCallback(() => {
    if (probe.current) {
      probe.current.abort();
      setProbeMessage("Поиск остановлен");
    }
    if (run.current) {
      run.current.abort();
      setStatus("Поездка остановлена");
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    const blur = () => stop(),
      key = (e: KeyboardEvent) => {
        if (e.key === "Escape") stop();
      },
      hidden = () => {
        if (document.hidden) stop();
      };
    window.addEventListener("blur", blur);
    window.addEventListener("keydown", key);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      mounted.current = false;
      probe.current?.abort();
      run.current?.abort();
      choice.current?.abort();
      window.removeEventListener("blur", blur);
      window.removeEventListener("keydown", key);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [stop]);
  useEffect(() => {
    if (!connected) {
      stop();
      probe.current?.abort();
      setObservation(null);
      setProbeMessage("");
    } else if (!ready && driving.current) {
      run.current?.abort();
      setStatus("Потерян свежий кадр. Управление остановлено.");
    }
  }, [connected, ready, stop]);
  async function inspect() {
    if (!ready || !video.current || run.current || probe.current) return;
    const c = new AbortController();
    probe.current = c;
    setProbing(true);
    setObservation(null);
    setProbeMessage("Ищем ориентиры в потоке…");
    try {
      const r = await probeWorldPosition(
        video.current,
        c.signal,
        acquireMinutes * 60_000,
        (frames, seconds, phase) => {
          if (!c.signal.aborted)
            setProbeMessage(
              `${searchPhases[phase ?? ""] ?? "Поиск ориентиров"} · ${frames} кадров. Осталось ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`,
            );
        },
      );
      if (!c.signal.aborted) {
        setObservation(r.eye);
        setProbeMessage(
          (r.district
            ? "Ориентиры · " + r.district
            : "Ориентиры у Кремля") +
            " · " +
            r.supports +
            " опор · " +
            new Date().toLocaleTimeString("ru-RU"),
        );
      }
    } catch (e) {
      if (!c.signal.aborted) setProbeMessage(problem(e));
    } finally {
      if (probe.current === c) probe.current = null;
      if (mounted.current) setProbing(false);
    }
  }
  useEffect(() => {
    const c = new AbortController();
    worldRequest<WorldInfo>(
      "/world",
      AbortSignal.any([c.signal, AbortSignal.timeout(6000)]),
    )
      .then((w) => {
        if (c.signal.aborted) return;
        setInfo(w);
        setStatus("Поставьте метку на дороге");
      })
      .catch((e) => {
        if (!c.signal.aborted) setStatus(problem(e));
      });
    return () => c.abort();
  }, [refresh]);
  const choose = useCallback(async (x: number, y: number) => {
    if (run.current) return;
    choice.current?.abort();
    const c = new AbortController();
    choice.current = c;
    setSuggestion(null);
    setCovered([]);
    setPoint([x, y]);
    setLevel(null);
    setLevels([]);
    setData(null);
    setAge(null);
    setStatus("Проверяем дорогу под меткой");
    try {
      const result = await worldRequest<{
        levels: number[];
        coveredLevels: number[];
        suggestion: { point: [number, number]; distance: number } | null;
      }>("/levels", AbortSignal.any([c.signal, AbortSignal.timeout(5000)]), {
        point: [x, y],
      });
      if (c.signal.aborted) return;
      setSuggestion(result.suggestion);
      const valid = result.levels;
      setCovered(result.coveredLevels);
      setLevels(valid);
      setLevel(valid.length === 1 ? valid[0] : null);
      setStatus(
        !result.levels.length
          ? "Под меткой нет проезжей дороги"
          : valid.length > 1
            ? "Выберите уровень дороги"
            : "Цель выбрана",
      );
    } catch (e) {
      if (!c.signal.aborted) setStatus(problem(e));
    }
  }, []);
  const [initialFocus, setInitialFocus] = useState<[number, number] | null>(null);
  useEffect(() => {
    if (!info) return;
    const target = new URL(window.location.href).searchParams.get("goal");
    if (!target) return;
    const fields = target.split(",");
    if (fields.length !== 2 || fields.some((v) => !v.trim())) return;
    const [x, y] = fields.map(Number);
    const [left, right, bottom, top] = info.bounds;
    if (!Number.isFinite(x) || !Number.isFinite(y) || x < left || x > right || y < bottom || y > top) return;
    setInitialFocus([x, y]);
    void choose(x, y);
    return () => choice.current?.abort();
  }, [info, choose]);
  function mark(x: number, y: number) {
    const url = new URL(window.location.href);
    url.searchParams.set("goal", [x.toFixed(4), y.toFixed(4)].join(","));
    window.history.replaceState(window.history.state, "", url);
    void choose(x, y);
  }
  async function start() {
    const el = video.current;
    if (
      !el ||
      !info ||
      (multiple
        ? itinerary.mode !== "drive" ||
          !itinerary.plan?.covered ||
          itinerary.plan.status !== "complete"
        : !point || level === null || !covered.includes(level)) ||
      inputIssue ||
      !ready ||
      run.current ||
      probe.current
    )
      return;
    const c = new AbortController();
    run.current = c;
    driving.current = false;
    setActive(true);
    setObservation(null);
    setProbeMessage("");
    setData(null);
    setAge(null);
    setStatus("Ищем скутер по живому кадру");
    let session: string | undefined;
    let applied = 0,
      rejected = 0;
    const journal = (e: TeachingInput) => {
      if (e.stage === "receipt") {
        if (e.outcome === "applied") applied++;
        else rejected++;
      }
    };
    try {
      // Retain the session handle even if Stop is pressed while /start is in flight.
      const res = await worldRequest<{ session: string }>(
        "/start",
        AbortSignal.timeout(5500),
        multiple
          ? {
              stops: itinerary.stops.map((p) => [...p.xy, p.z]),
              revision: info.mapRevision,
            }
          : { goal: [...point!, level], revision: info.mapRevision },
      );
      session = res.session;
      if (!c.signal.aborted)
        await runWorldTrip(
          el,
          session,
          c.signal,
          () => opening.current(c.signal, journal),
          (d, ms) => {
            if (!c.signal.aborted) {
              if (d.reason === "following" && ms < 320) driving.current = true;
              setData(d);
              setAge(ms);
              setStatus(
                ms >= 320
                  ? "Ответ по устаревшему кадру"
                  : (d.reason === "position_unknown" && d.worldSearch
                      ? (searchPhases[d.worldSearch.phase] ?? reasons.position_unknown)
                      : (reasons[d.reason] ?? d.reason)),
              );
            }
          },
          acquireMinutes * 60_000,
        );
    } catch (e) {
      if (!c.signal.aborted && mounted.current) setStatus(problem(e));
    } finally {
      if (session)
        await worldRequest(
          "/stop",
          AbortSignal.timeout(3000),
          { applied, rejected },
          session,
        ).catch(() => undefined);
      if (run.current === c) {
        run.current = null;
        driving.current = false;
      }
      if (mounted.current) setActive(false);
    }
  }
  const eligible = multiple
    ? itinerary.mode === "drive" &&
      itinerary.plan?.status === "complete" &&
      itinerary.plan.covered
    : level !== null && covered.includes(level);
  function switchPlan(value: boolean) {
    choice.current?.abort();
    setMultiple(value);
    setData(null);
    setStatus("");
  }
  return (
    <section aria-label="Поездка к метке" className={styles.panel}>
      <header className={styles.panelHeader}>
        <div>
          <MapPin size={17} />
          <h2>Карта мира</h2>
        </div>
        <nav className={styles.planTabs} aria-label="Выбор маршрута">
          {[
            [false, "К метке"],
            [true, "A–B–C"],
          ].map(([value, label]) => (
            <button
              key={String(label)}
              aria-pressed={multiple === value}
              disabled={active}
              onClick={() => switchPlan(value === true)}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      {info ? (
        <WorldDestinationMap
          info={info}
          point={multiple ? null : point}
          initialFocus={initialFocus}
          observation={observation}
          decision={data}
          stops={multiple ? itinerary.stops : []}
          legs={multiple ? itinerary.plan?.legs : undefined}
          onChoose={(x, y) => {
            if (!run.current) {
              if (multiple) itinerary.add(x, y);
              else mark(x, y);
            }
          }}
        />
      ) : (
        <div className={styles.mapLoading}>
          <p>{status}</p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRefresh((n) => n + 1)}
          >
            Повторить подключение к карте
          </Button>
        </div>
      )}
      <div className={styles.tripFooter}>
        {multiple ? (
          <WorldItinerary model={itinerary} locked={active} />
        ) : (
          <>
            <div className={styles.target}>
              <Flag size={17} />
              <div>
                <strong>
                  {point ? "Точка назначения" : "Выберите точку назначения"}
                </strong>
                <p>
                  {point
                    ? point.map((n) => n.toFixed(1)).join(" / ")
                    : "Щелчок ставит метку. Перетаскивание перемещает карту."}
                </p>
              </div>
              {point && !active && (
                <button
                  aria-label="Сбросить метку"
                  onClick={() => {
                    choice.current?.abort();
                    setPoint(null);
                    setLevel(null);
                    setLevels([]);
                    setSuggestion(null);
                    setData(null);
                    setStatus("");
                  }}
                >
                  <X size={15} />
                </button>
              )}
            </div>
            {levels.length > 1 && (
              <label className={styles.selectLabel}>
                Уровень дороги{" "}
                <select
                  disabled={active}
                  value={level ?? ""}
                  onChange={(e) => setLevel(Number(e.target.value))}
                >
                  <option value="" disabled>
                    Выберите
                  </option>
                  {levels.map((z) => (
                    <option key={z} value={z}>
                      {z.toFixed(1)} м
                    </option>
                  ))}
                </select>
              </label>
            )}
            {suggestion && !active && (
              <Button
                className={styles.suggest}
                size="sm"
                variant="outline"
                onClick={() => mark(...suggestion.point)}
              >
                Выбрать дорогу рядом · {suggestion.distance.toFixed(1)} м
              </Button>
            )}
          </>
        )}
        {(active || (point && !multiple) || data) && status && (
          <p role="status" className={styles.status}>
            {status}
            {multiple && data?.stopIndex != null
              ? " · " + letter(data.stopIndex)
              : ""}
          </p>
        )}
        {((!multiple && point && level !== null && !eligible) ||
          (multiple && itinerary.plan?.status === "complete" && !eligible)) && (
          <p className={styles.attention}>
            {multiple
              ? "Путь рассчитан. Автопоездка доступна на транспортных участках с проверенными ориентирами."
              : "Дорога найдена. Для автопоездки здесь ещё нужны визуальные ориентиры."}
          </p>
        )}
        {data && (
          <p className={styles.status}>
            Опор {data.pose?.supports ?? 0} · Кадр до решения {age} мс
            {data.remaining != null
              ? " · Осталось " + data.remaining.toFixed(1) + " м"
              : ""}
          </p>
        )}
        <div className={styles.tripAction}>
          {active ? (
            <Button variant="destructive" onClick={stop}>
              Остановить · Esc
            </Button>
          ) : (
            <Button
              disabled={!ready || !!inputIssue || !eligible || probing}
              onClick={() => void start()}
            >
              <Navigation size={15} />
              {multiple ? "Ехать по точкам" : "Ехать к метке"}
            </Button>
          )}
          {!active && inputIssue && (
            <small>
              {!ready ? (
                <a href="#destination-stream">{inputIssue}</a>
              ) : (
                inputIssue
              )}
            </small>
          )}
        </div>
        <div className={styles.probeLine}>
          <Button
            size="sm"
            variant="ghost"
            disabled={!ready || !info || active}
            onClick={() => (probing ? stop() : void inspect())}
          >
            <LocateFixed size={15} />
            {probing ? "Остановить поиск" : "Определить положение"}
          </Button>
          {probeMessage && <small role="status">{probeMessage}</small>}
        </div>
        <details className={styles.previewOptions}>
          <summary>Параметры поиска</summary>
          <label className={styles.selectLabel}>
            Время на поиск позиции
            <select
              disabled={active || probing}
              value={acquireMinutes}
              onChange={(e) => setAcquireMinutes(Number(e.target.value))}
            >
              {[1, 3, 5].map((n) => (
                <option key={n} value={n}>
                  {n} мин
                </option>
              ))}
            </select>
          </label>
        </details>
      </div>
    </section>
  );
}
