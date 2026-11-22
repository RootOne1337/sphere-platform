"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { worldRequest, type XYZ } from "./worldDestination";
import styles from "./worldConsole.module.css";

export type TravelMode = "drive" | "walk" | "taxi";
type Levels = {
  levels: number[];
  driveLevels: number[];
  walkLevels: number[];
  suggestion: { point: [number, number]; distance: number } | null;
};
export type RoadLeg = {
  mode: "drive" | "walk";
  fromIndex: number;
  distance: number;
  path: XYZ[];
  crossings?: { entry: XYZ; exit: XYZ }[];
};
export type RoutePlan = {
  status: "complete" | "unavailable";
  legs: RoadLeg[];
  distance?: number;
  covered?: boolean;
  reason?: string;
  stop?: number;
};
export type Stop = {
  id: string;
  xy: [number, number];
  z: number | null;
  preferredLevel?: number;
  mode?: TravelMode;
  ground?: Levels;
  error?: string;
};
export const letter = (i: number) => String.fromCharCode(65 + i);

export function useWorldItinerary(revision: string | undefined) {
  const [mode, setMode] = useState<TravelMode>("drive"),
    [stops, setStops] = useState<Stop[]>([]);
  const [plan, setPlan] = useState<RoutePlan | null>(null),
    [error, setError] = useState("");
  const terrain = useRef(new Map<string, AbortController>());
  const pending = useRef(new Map<string, string>());
  useEffect(() => {
    const requests = terrain.current,
      keys = pending.current;
    return () => {
      requests.forEach((c) => c.abort());
      requests.clear();
      keys.clear();
    };
  }, []);
  useEffect(() => {
    for (const [id, c] of terrain.current) {
      if (!stops.some((p) => p.id === id)) {
        c.abort();
        terrain.current.delete(id);
        pending.current.delete(id);
      }
    }
    for (const stop of stops) {
      const signature = JSON.stringify([mode, stop.xy]);
      if (pending.current.get(stop.id) === signature) continue;
      terrain.current.get(stop.id)?.abort();
      const c = new AbortController();
      terrain.current.set(stop.id, c);
      pending.current.set(stop.id, signature);
      worldRequest<Levels>(
        "/levels",
        AbortSignal.any([c.signal, AbortSignal.timeout(5000)]),
        { point: stop.xy, mode, ...(mode === "walk" ? { surface: "pavement" } : {}) },
      )
        .then((ground) => {
          if (!c.signal.aborted)
            setStops((list) =>
              list.map((p) =>
                p.id !== stop.id
                  ? p
                  : {
                      ...p,
                      mode,
                      ground,
                      error: undefined,
                      z: p.preferredLevel !== undefined
                        ? ground.levels.find((z) => Math.abs(z - p.preferredLevel!) <= 0.2) ?? null
                        : ground.levels.length === 1 ? ground.levels[0] : null,
                    },
              ),
            );
        })
        .catch(() => {
          if (!c.signal.aborted)
            setStops((list) =>
              list.map((p) =>
                p.id !== stop.id
                  ? p
                  : {
                      ...p,
                      mode,
                      ground: undefined,
                      z: null,
                      error: "Служба карты недоступна",
                    },
              ),
            );
        });
    }
  }, [mode, stops]);
  useEffect(() => {
    setPlan(null);
    setError("");
    if (
      !revision ||
      stops.length < 2 ||
      stops.some((p) => p.mode !== mode || p.z === null)
    )
      return;
    const c = new AbortController();
    const timer = setTimeout(() => {
      worldRequest<RoutePlan>(
        "/itinerary",
        AbortSignal.any([c.signal, AbortSignal.timeout(300000)]),
        { revision, mode, stops: stops.map((p) => [...p.xy, p.z]),
          ...(mode === "walk" ? { surface: "crossings" } : {}) },
      )
        .then((r) => {
          if (!c.signal.aborted) setPlan(r);
        })
        .catch(() => {
          if (!c.signal.aborted) setError("Не удалось рассчитать маршрут");
        });
    }, 120);
    return () => {
      clearTimeout(timer);
      c.abort();
    };
  }, [mode, revision, stops]);
  const add = useCallback(
    (x: number, y: number) =>
      setStops((list) =>
        list.length >= 18
          ? list
          : [...list, { id: crypto.randomUUID(), xy: [x, y], z: null }],
      ),
    [],
  );
  function useLiveStart(point: XYZ, mode: Exclude<TravelMode, "taxi">) {
    const first: Stop = {
      id: crypto.randomUUID(), xy: [point[0], point[1]], z: null, preferredLevel: point[2], mode,
    };
    setMode(mode);
    setStops((list) => [first, ...list.slice(1)]);
  }
  function revise(id: string, patch: Partial<Stop>) {
    setStops((list) => list.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }
  function move(i: number, delta: number) {
    setStops((list) => {
      const next = [...list];
      if (i + delta < 0 || i + delta >= next.length) return list;
      [next[i], next[i + delta]] = [next[i + delta], next[i]];
      return next;
    });
  }
  function retry(id: string) {
    pending.current.delete(id);
    revise(id, { mode: undefined, error: undefined });
  }
  return {
    mode,
    setMode,
    stops,
    plan,
    error,
    add,
    useLiveStart,
    revise,
    move,
    retry,
    remove: (id: string) => setStops((list) => list.filter((p) => p.id !== id)),
  };
}
export function WorldItinerary({
  model,
  locked,
}: {
  model: ReturnType<typeof useWorldItinerary>;
  locked: boolean;
}) {
  const { mode, setMode, stops, plan, revise, move, retry, remove } = model;
  const complete = plan?.status === "complete";
  const unresolved = stops.some((p) => p.z === null || p.mode !== mode);
  return (
    <div className={styles.itinerary}>
      <label className={styles.selectLabel}>
        Способ передвижения
        <select
          aria-label="Способ передвижения"
          disabled={locked}
          value={mode}
          onChange={(e) => setMode(e.target.value as TravelMode)}
        >
          <option value="drive">Транспорт</option>
          <option value="walk">Пешком по тротуарам</option>
          <option value="taxi">Пешком и на транспорте</option>
        </select>
      </label>
      {!stops.length && (
        <p>
          Нажмите на карту для точки A, затем добавьте B и следующие остановки.
        </p>
      )}
      {stops.length > 0 && (
        <ol>
          {stops.map((p, i) => (
            <li key={p.id}>
              <b>{letter(i)}</b>
              <div>
                <strong>{p.xy.map((v) => v.toFixed(1)).join(" / ")}</strong>
                <small>
                  {p.mode !== mode
                    ? "Проверяем поверхность"
                    : p.error ||
                      (!p.ground?.levels.length
                        ? "Точка вне выбранной поверхности"
                        : p.z === null
                          ? "Выберите уровень"
                          : p.ground.driveLevels.some(
                                (z) => Math.abs(z - p.z!) < 0.45,
                              )
                            ? "Есть проезд"
                            : "Пешая поверхность")}
                </small>
                {p.ground && p.mode === mode && p.ground.levels.length > 1 && (
                  <select
                    aria-label={"Высота " + letter(i)}
                    disabled={locked}
                    value={p.z ?? ""}
                    onChange={(e) =>
                      revise(p.id, { z: Number(e.target.value) })
                    }
                  >
                    <option value="" disabled>
                      Уровень
                    </option>
                    {p.ground.levels.map((z) => (
                      <option key={z} value={z}>
                        {z.toFixed(1)} м
                      </option>
                    ))}
                  </select>
                )}
                {p.ground?.suggestion && p.mode === mode && (
                  <button
                    disabled={locked}
                    onClick={() =>
                      revise(p.id, {
                        xy: p.ground!.suggestion!.point,
                        z: null,
                        mode: undefined,
                        ground: undefined,
                      })
                    }
                  >
                    Рядом · {p.ground.suggestion.distance} м
                  </button>
                )}
                {p.error && (
                  <button onClick={() => retry(p.id)} disabled={locked}>
                    Повторить
                  </button>
                )}
              </div>
              <button
                aria-label={"Переместить " + letter(i) + " выше"}
                disabled={locked || i === 0}
                onClick={() => move(i, -1)}
              >
                <ArrowUp size={15} />
              </button>
              <button
                aria-label={"Переместить " + letter(i) + " ниже"}
                disabled={locked || i === stops.length - 1}
                onClick={() => move(i, 1)}
              >
                <ArrowDown size={15} />
              </button>
              <button
                aria-label={"Удалить " + letter(i)}
                disabled={locked}
                onClick={() => remove(p.id)}
              >
                <X size={15} />
              </button>
            </li>
          ))}
        </ol>
      )}
      <p role="status">
        {model.error ||
          (complete
            ? "Маршрут построен · " +
              Math.round(plan.distance ?? 0).toLocaleString("ru-RU") +
              " м · " +
              stops.length +
              " точки"
            : plan?.status === "unavailable"
              ? (plan.reason === "wrong_surface"
                  ? "Неподходящая поверхность в точке "
                  : plan.reason === "surface_unconfirmed"
                  ? "До точки есть участок без подтверждённого тротуара или перехода "
                  : "Нет связного пути к точке ") + letter(plan.stop ?? 0)
              : stops.length === 18
                ? "Достигнут предел в 18 точек"
                : stops.length === 1
                  ? "Выберите следующую точку на карте"
                  : stops.length >= 2 && !unresolved
                    ? "Строим маршрут…"
                    : "")}
      </p>
      {complete && (
        <small>
          {plan.legs
            .map(
              (l) =>
                (l.mode === "walk" ? "Пешком" : "На транспорте") +
                " " +
                Math.round(l.distance) +
                " м",
            )
            .join(" · ")}
        </small>
      )}
    </div>
  );
}
