"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { Flag, Footprints, LocateFixed, MapPin, Navigation, X } from "lucide-react";
import { runWorldWalk } from "./worldWalk";
import { WorldDestinationMap } from "./WorldDestinationMap";
import styles from "./worldConsole.module.css";
import { Button } from "@/components/ui/button";
import type { TeachingInput } from "./teachingContacts";
import type { WalkInputLease } from "./walkPilot";
import type { VehicleInputLease } from "./vehiclePilot";
import {
  probeWorldPosition,
  runWorldTrip,
  worldRequest,
  type Decision,
  type StartLevels,
  type WorldInfo,
  type XYZ,
} from "./worldDestination";

import { WorldItinerary, useWorldItinerary, letter, type RoutePlan } from "./WorldItinerary";

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
  menu_backdrop: "В кадре фон меню игры. Войдите в игровой мир для поиска положения.",
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
  world_camera_unavailable: "Канал поворота камеры недоступен",
  world_camera_no_motion: "После команд поворота ракурс в игре не изменился",
  walk_input_not_ready: "Поворот камеры требует настроенного пешего управления",
  stream_stopped: "Поток остановлен",
  stream_geometry_or_clock: "Нужен свежий горизонтальный кадр 16:9",
  unreachable_goal: "Метка вне проезжей части",
  planning_walk: "Прокладываем маршрут по тротуарам и переходам",
  walking: "Идём к метке",
  walk_aligning: "Поворачиваем камеру по ходу маршрута",
  walk_outside_path: "Уточняем положение и перестраиваем маршрут",
  walk_clearance_unknown: "Не подтверждён проход впереди. Остановились для проверки.",
  walk_start_not_on_pavement: "Положение найдено. Под персонажем нет подтверждённого тротуара.",
  walk_path_unavailable: "Между текущим тротуаром и меткой нет подтверждённого пешеходного пути.",
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
  openCamera,
  cameraIssue,
  walkIssue,
  openWalk,
}: {
  video: RefObject<HTMLVideoElement | null>;
  ready: boolean;
  connected: boolean;
  inputIssue: string | null;
  cameraIssue?: string | null;
  openCamera?: (signal: AbortSignal, journal: (event: TeachingInput) => void) => Promise<WalkInputLease>;
  walkIssue?: string | null;
  openWalk?: (signal: AbortSignal, journal: (event: TeachingInput) => void) => Promise<WalkInputLease>;
  openInput: (
    signal: AbortSignal,
    journal: (event: TeachingInput) => void,
  ) => Promise<VehicleInputLease>;
}) {
  const [probing, setProbing] = useState(false),
    [probeMessage, setProbeMessage] = useState("");
  const [observation, setObservation] = useState<{
    eye: XYZ; startLevels: StartLevels; acquiredAt: number;
  } | null>(null);
  const probe = useRef<AbortController | null>(null);
  const [info, setInfo] = useState<WorldInfo | null>(null);
  const [suggestion, setSuggestion] = useState<{
    point: [number, number];
    distance: number;
  } | null>(null);
  const [covered, setCovered] = useState<number[]>([]);
  const [multiple, setMultiple] = useState(false);
  const [walking, setWalking] = useState(() =>
    typeof window !== "undefined" && new URL(window.location.href).searchParams.get("travel") === "walk",
  );
  const [acquireMinutes, setAcquireMinutes] = useState(3);
  const itinerary = useWorldItinerary(info?.mapRevision);
  const [liveStartFresh, setLiveStartFresh] = useState(false);
  useEffect(() => {
    if (!observation) {
      setLiveStartFresh(false);
      return;
    }
    const expires = observation.acquiredAt + 30000 - performance.now();
    setLiveStartFresh(expires > 0);
    const timer = setTimeout(() => setLiveStartFresh(false), Math.max(0, expires));
    return () => clearTimeout(timer);
  }, [observation]);
  const [point, setPoint] = useState<[number, number] | null>(null),
    [levels, setLevels] = useState<number[]>([]),
    [level, setLevel] = useState<number | null>(null);
  const [status, setStatus] = useState("Загрузка карты"),
    [active, setActive] = useState(false),
    [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Decision | null>(null),
    [age, setAge] = useState<number | null>(null);
  const [commandAge, setCommandAge] = useState<number | null>(null);
  const [preview, setPreview] = useState<RoutePlan | "pending" | "error" | null>(null);
  useEffect(() => {
    setPreview(null);
    if (!info || !walking || multiple || !observation || !liveStartFresh ||
        !point || level === null || observation.startLevels.walk === null || active) return;
    const controller = new AbortController();
    setPreview("pending");
    void worldRequest<RoutePlan>(
      "/itinerary",
      AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
      {
        revision: info.mapRevision,
        mode: "walk",
        surface: "crossings",
        stops: [
          [observation.eye[0], observation.eye[1], observation.startLevels.walk],
          [...point, level],
        ],
      },
    ).then(
      (plan) => { if (!controller.signal.aborted) setPreview(plan); },
      () => { if (!controller.signal.aborted) setPreview("error"); },
    );
    return () => controller.abort();
  }, [info, walking, multiple, observation, liveStartFresh, point, level, active]);
  const choice = useRef<AbortController | null>(null),
    run = useRef<AbortController | null>(null),
    mounted = useRef(false);
  const driving = useRef(false);
  const surveying = useRef(false);
  const opening = useRef(openInput);
  opening.current = openInput;
  const stop = useCallback(() => {
    if (probe.current) {
      probe.current.abort();
      setProbeMessage("Поиск остановлен");
    }
    if (run.current) {
      run.current.abort();
      setStatus("Проход остановлен");
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    const blur = () => {
        if (run.current && !surveying.current) stop();
      },
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
        ({ frames, secondsLeft: seconds, phase, cameraSteps, cameraTurns, cameraIssue: issue }) => {
          if (!c.signal.aborted)
            setProbeMessage(
              `${issue ? problem(Error(issue)) + ". " : ""}${searchPhases[phase ?? ""] ?? "Собираем ракурсы"}. Кадров ${frames}, поворотов ${cameraTurns} из ${cameraSteps}. Осталось ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`,
            );
        },
        !cameraIssue && openCamera ? (signal) => openCamera(signal, () => {}) : undefined,
        info?.worldSearch,
        undefined,
        walking || (multiple && itinerary.mode === "walk"),
      );
      if (!c.signal.aborted) {
        setObservation({ eye: r.eye, startLevels: r.startLevels, acquiredAt: performance.now() });
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
    setCommandAge(null);
    setStatus(walking ? "Проверяем тротуар под меткой" : "Проверяем дорогу под меткой");
    try {
      const result = await worldRequest<{
        levels: number[];
        coveredLevels: number[];
        suggestion: { point: [number, number]; distance: number } | null;
      }>("/levels", AbortSignal.any([c.signal, AbortSignal.timeout(5000)]), {
        point: [x, y],
        ...(walking ? { mode: "walk", surface: "pavement" } : {}),
      });
      if (c.signal.aborted) return;
      setSuggestion(result.suggestion);
      const valid = result.levels;
      setCovered(result.coveredLevels);
      setLevels(valid);
      setLevel(valid.length === 1 ? valid[0] : null);
      setStatus(
        !result.levels.length
          ? (walking ? "Под меткой нет тротуара" : "Под меткой нет проезжей дороги")
          : valid.length > 1
            ? (walking ? "Выберите уровень тротуара" : "Выберите уровень дороги")
            : "Цель выбрана",
      );
    } catch (e) {
      if (!c.signal.aborted) setStatus(problem(e));
    }
  }, [walking]);
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
  const walkItinerary = multiple && itinerary.mode === "walk";
  const onFoot = walkItinerary || (walking && !multiple);
  const eligible = walkItinerary
    ? info?.walkAutopilot === true && itinerary.stops.length > 0 &&
      itinerary.stops.every((stop) => stop.mode === "walk" && stop.z !== null)
    : multiple
      ? itinerary.mode === "drive" && itinerary.plan?.status === "complete" && itinerary.plan.covered
      : level !== null && !!point && (onFoot ? info?.walkAutopilot === true : covered.includes(level));
  const currentIssue = onFoot ? walkIssue ?? cameraIssue : inputIssue;
  async function start() {
    const el = video.current;
    if (
      !el ||
      !info ||
      !eligible || currentIssue || (onFoot && (!openWalk || !openCamera)) ||
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
    setCommandAge(null);
    setStatus(onFoot ? "Ищем положение персонажа по живому кадру" : "Ищем скутер по живому кадру");
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
      const locateWalkingStart = async () => {
        surveying.current = true;
        try {
          const position = await probeWorldPosition(
            el, c.signal, acquireMinutes * 60_000,
            ({ phase, frames, cameraSteps, cameraTurns, cameraIssue: issue }) => {
              if (!c.signal.aborted) setStatus(
                `${issue ? problem(Error(issue)) + ". " : ""}${searchPhases[phase ?? ""] ?? "Сбор ракурсов"} · ${frames} кадров · поворотов ${cameraTurns} из ${cameraSteps}`,
              );
            },
            (signal) => openCamera!(signal, journal),
            info.worldSearch,
            session,
            true,
          );
          if (!c.signal.aborted) {
            setObservation({ eye: position.eye, startLevels: position.startLevels, acquiredAt: performance.now() });
            setStatus("Положение подтверждено. Готовим пеший маршрут");
          }
        } finally {
          surveying.current = false;
        }
      };
      if (onFoot) await locateWalkingStart();
      if (c.signal.aborted) return;
      // Retain the session handle even if Stop is pressed while /start is in flight.
      const res = await worldRequest<{ session: string }>(
        "/start",
        AbortSignal.timeout(5500),
        multiple
          ? {
              stops: itinerary.stops.map((p) => [...p.xy, p.z]),
              revision: info.mapRevision,
              ...(walkItinerary ? { mode: "walk" } : {}),
            }
          : { goal: [...point!, level], revision: info.mapRevision, ...(onFoot ? { mode: "walk" } : {}) },
      );
      session = res.session;
      if (!c.signal.aborted && onFoot)
        await runWorldWalk(el, session, c.signal, () => openWalk!(c.signal, journal),
          (decision, ms, commandMs) => {
            if (c.signal.aborted) return;
            setData(decision);
            setAge(ms);
            if (commandMs != null) setCommandAge(commandMs);
            setStatus(ms >= 250 && decision.reason === "walking"
              ? "Кадр для шага устарел. Ждём новое решение."
              : decision.reason === "no_motion"
              ? "Пеший проход остановлен. Персонаж не продвинулся после команды."
              : reasons[decision.reason] ?? decision.reason);
          }, locateWalkingStart);
      else if (!c.signal.aborted)
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
  const previewLegs = preview && typeof preview !== "string" && preview.status === "complete"
    ? preview.legs
    : undefined;
  function switchPlan(value: "drive" | "walk" | "itinerary") {
    choice.current?.abort();
    if (value !== "itinerary") {
      const url = new URL(window.location.href);
      if (value === "walk") url.searchParams.set("travel", "walk");
      else url.searchParams.delete("travel");
      window.history.replaceState(window.history.state, "", url);
    }
    setMultiple(value === "itinerary");
    setWalking(value === "walk");
    setData(null);
    setStatus("");
  }
  return (
    <section aria-label="Навигация к метке" className={styles.panel}>
      <header className={styles.panelHeader}>
        <div>
          <MapPin size={17} />
          <h2>Карта мира</h2>
        </div>
        <nav className={styles.planTabs} aria-label="Выбор маршрута">
          {([
            ["drive", "На транспорте"],
            ["walk", "Пешком"],
            ["itinerary", "A–B–C"],
          ] as const).map(([value, label]) => (
            <button
              key={String(label)}
              aria-pressed={value === (multiple ? "itinerary" : walking ? "walk" : "drive")}
              disabled={active || probing}
              onClick={() => switchPlan(value)}
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
          observation={observation?.eye ?? null}
          decision={data}
          stops={multiple ? itinerary.stops : []}
          legs={multiple ? itinerary.plan?.legs : previewLegs}
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
          <>
            {observation && liveStartFresh && ready && !active && itinerary.mode === "drive" && (
              <div className={styles.tripAction}>
                <Button size="sm" variant="outline" disabled={observation.startLevels.drive === null} onClick={() => {
                  const z = observation.startLevels.drive;
                  if (z === null || performance.now() - observation.acquiredAt >= 30000) return;
                  itinerary.useLiveStart([observation.eye[0], observation.eye[1], z], "drive");
                }}>
                  Поставить A на дороге
                </Button>
              </div>
            )}
            <WorldItinerary model={itinerary} locked={active} />
          </>
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
                    const url = new URL(window.location.href);
                    url.searchParams.delete("goal");
                    window.history.replaceState(window.history.state, "", url);
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
                {walking ? "Уровень тротуара" : "Уровень дороги"}{" "}
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
                {walking ? "Выбрать тротуар рядом" : "Выбрать дорогу рядом"} · {suggestion.distance.toFixed(1)} м
              </Button>
            )}
            {preview && (
              <div role="status" className={styles.walkPreview}>
                <Footprints size={16} />
                <div>
                  <strong>{previewLegs ? "Пеший маршрут" : "Проверка пешего маршрута"}</strong>
                  <p>
                    {preview === "pending" ? "Проверяем тротуары и переходы"
                      : preview === "error" ? "Служба карты не вернула маршрут"
                      : preview.reason === "surface_unconfirmed" ? "На пути есть участок без подтверждённого тротуара или перехода"
                      : preview.status === "unavailable" ? "Между этими точками нет связного пешего пути"
                      : `${Math.round(preview.distance ?? 0)} м · переходов ${preview.legs.reduce((n, leg) => n + (leg.crossings?.length ?? 0), 0)}`}
                  </p>
                </div>
              </div>
            )}
          </>
        )}
        {(active || (point && !multiple) || data) && status && (!preview || status !== "Цель выбрана") && (
          <p role="status" className={styles.status}>
            {status}
            {multiple && data?.stopIndex != null
              ? " · " + letter(data.stopIndex)
              : ""}
          </p>
        )}
        {((walkItinerary && itinerary.stops.length > 0 && !info?.walkAutopilot) ||
          (!multiple && point && level !== null && !eligible) ||
          (multiple && itinerary.plan?.status === "complete" && !eligible)) && (
          <p className={styles.attention}>
            {onFoot ? "Служба карты не поддерживает пешее управление."
              : multiple
              ? "Путь рассчитан. Автопоездка доступна на транспортных участках с проверенными ориентирами."
              : "Дорога найдена. Для автопоездки здесь ещё нужны визуальные ориентиры."}
          </p>
        )}
        {data && (
          <p className={styles.status}>
            Опор {data.pose?.supports ?? 0} · Кадр до решения {age} мс
            {onFoot && commandAge != null && ` · Кадр до команды ${commandAge} мс`}
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
              disabled={!ready || !!currentIssue || !eligible || probing}
              onClick={() => void start()}
            >
              {onFoot ? <Footprints size={15} /> : <Navigation size={15} />}
              {multiple ? (onFoot ? "Идти по точкам" : "Ехать по точкам") : onFoot ? "Идти к метке" : "Ехать к метке"}
            </Button>
          )}
          {!active && currentIssue && (
            <small>
              {!ready ? (
                <a href="#destination-stream">{currentIssue}</a>
              ) : (
                currentIssue
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
          {cameraIssue && !probing && <small>{cameraIssue}</small>}
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
