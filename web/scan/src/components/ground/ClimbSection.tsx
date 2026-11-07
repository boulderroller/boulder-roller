import { useEffect, useRef, useState } from "react";
import type { CanonicalProfileSample } from "@/types";
export function validProfile(profile: CanonicalProfileSample[]) {
  return (
    profile.length >= 2 &&
    profile.every(
      (p, i) =>
        Number.isFinite(p.dist_m) &&
        Number.isFinite(p.elev_m) &&
        (i === 0 || p.dist_m > profile[i - 1].dist_m),
    )
  );
}
export function elevationAt(profile: CanonicalProfileSample[], d: number) {
  if (d <= profile[0].dist_m) return profile[0].elev_m;
  for (let i = 1; i < profile.length; i++)
    if (profile[i].dist_m >= d) {
      const a = profile[i - 1],
        b = profile[i];
      return (
        a.elev_m +
        ((b.elev_m - a.elev_m) * (d - a.dist_m)) / (b.dist_m - a.dist_m)
      );
    }
  return profile.at(-1)!.elev_m;
}
export function ClimbGlyph({ profile }: { profile: CanonicalProfileSample[] }) {
  if (!validProfile(profile)) return null;
  const min = Math.min(...profile.map((p) => p.elev_m)),
    span = Math.max(...profile.map((p) => p.elev_m)) - min;
  const first = profile[0].dist_m,
    length = profile.at(-1)!.dist_m - first;
  const line = profile
    .map(
      (p) =>
        `${((p.dist_m - first) / length) * 40},${18 - ((p.elev_m - min) / (span || 1)) * 17}`,
    )
    .join(" ");
  return (
    <svg viewBox="0 0 40 20" aria-hidden="true">
      <polygon points={`0,20 ${line} 40,20`} fill="#4E4B46" />
      <polyline
        points={line}
        fill="none"
        stroke="#F1EEE8"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}
/** Board's 100m bands, relative section, luminance/weight steps and clearance rules. */
export default function ClimbSection({
  profile,
  name,
  distance,
  onInspect,
}: {
  profile: CanonicalProfileSample[];
  name: string;
  distance: number | null;
  onInspect: (d: number | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    [width, setWidth] = useState(1440);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(() =>
      setWidth(host.current!.clientWidth),
    );
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  if (!validProfile(profile)) return null;
  const phone = width < 700,
    W = width,
    H = phone ? 118 : 176,
    left = phone ? 16 : 40,
    right = phone ? 16 : 64,
    top = phone ? 22 : 26,
    bottom = phone ? 26 : 30;
  const start = profile[0].dist_m,
    L = profile.at(-1)!.dist_m - start,
    es = profile.map((p) => p.elev_m),
    min = Math.min(...es),
    max = Math.max(...es),
    gain = max - min,
    base = H - bottom;
  const X = (d: number) => left + ((d - start) / L) * (W - left - right),
    Y = (e: number) => base - ((e - min) / (gain * 1.06 || 1)) * (base - top);
  const bands: { d0: number; d1: number; r: number }[] = [];
  const rung = (g: number) =>
    g >= 12 ? 4 : g >= 9 ? 3 : g >= 6 ? 2 : g >= 3 ? 1 : 0;
  for (let d = start; d < start + L; d += 100) {
    const end = Math.min(d + 100, start + L),
      r = rung(
        ((elevationAt(profile, end) - elevationAt(profile, d)) / (end - d)) *
          100,
      ),
      prev = bands.at(-1);
    if (prev?.r === r) prev.d1 = end;
    else bands.push({ d0: d, d1: end, r });
  }
  const stroke = ["#4E4B46", "#6A6660", "#9A9488", "#F1EEE8", "#F1EEE8"],
    weight = [1.6, 1.8, 2, 2.2, 3];
  const line = (points: CanonicalProfileSample[]) =>
    points.map((p) => `${X(p.dist_m)},${Y(p.elev_m)}`).join(" ");
  const relative =
      distance === null ? null : Math.max(start, Math.min(start + L, distance)),
    e = relative === null ? null : elevationAt(profile, relative);
  const inspect = (clientX: number) => {
    const bounds = host.current!.getBoundingClientRect();
    onInspect(
      start +
        Math.max(
          0,
          Math.min(1, (clientX - bounds.left - left) / (W - left - right)),
        ) *
          L,
    );
  };
  return (
    <div
      ref={host}
      className="climb-section"
      onPointerMove={(event) => {
        if (event.buttons === 0 || event.pointerType === "mouse")
          inspect(event.clientX);
      }}
      onClick={(event) => inspect(event.clientX)}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="slider"
        tabIndex={0}
        aria-label="Climb route and elevation"
        aria-valuemin={0}
        aria-valuemax={Math.round(L)}
        aria-valuenow={Math.round((relative ?? start) - start)}
        onKeyDown={(event) => {
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            onInspect(
              event.key === "Home"
                ? start
                : event.key === "End"
                  ? start + L
                  : Math.min(
                      start + L,
                      Math.max(
                        start,
                        (relative ?? start) +
                          (event.key === "ArrowRight" ? 25 : -25),
                      ),
                    ),
            );
          }
        }}
      >
        <title>{name}</title>
        {Array.from(
          { length: Math.floor(gain / (gain > 80 ? 20 : 10)) },
          (_, i) => (i + 1) * (gain > 80 ? 20 : 10),
        ).map((v) => (
          <g key={v}>
            <line
              x1={left}
              x2={W - right}
              y1={Y(min + v)}
              y2={Y(min + v)}
              stroke="#4E4B46"
              strokeOpacity=".28"
            />
            {!phone && (
              <text x={W - right + 8} y={Y(min + v) + 4} fill="#6A6660">
                {v} m
              </text>
            )}
          </g>
        ))}
        <polygon
          points={`${X(start)},${base} ${line(profile)} ${X(start + L)},${base}`}
          fill="#201F1B"
        />
        {bands.map((b, i) => {
          const mid = (b.d0 + b.d1) / 2,
            g =
              ((elevationAt(profile, b.d1) - elevationAt(profile, b.d0)) /
                (b.d1 - b.d0)) *
              100;
          const points = [
            { dist_m: b.d0, elev_m: elevationAt(profile, b.d0) },
            ...profile.filter((p) => p.dist_m > b.d0 && p.dist_m < b.d1),
            { dist_m: b.d1, elev_m: elevationAt(profile, b.d1) },
          ];
          return (
            <g key={b.d0}>
              {i > 0 && (
                <line
                  x1={X(b.d0)}
                  x2={X(b.d0)}
                  y1={Y(elevationAt(profile, b.d0))}
                  y2={base}
                  stroke="#2A2825"
                />
              )}
              <polyline
                points={line(points)}
                fill="none"
                stroke={stroke[b.r]}
                strokeWidth={weight[b.r]}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {X(b.d1) - X(b.d0) >= 44 &&
                base - Y(elevationAt(profile, mid)) >= 20 && (
                  <text
                    x={X(mid)}
                    y={base - 7}
                    textAnchor="middle"
                    fill={b.r < 1 ? "#6A6660" : b.r < 2 ? "#9A9488" : "#F1EEE8"}
                    fontWeight="600"
                  >
                    {g.toFixed(1)}%
                  </text>
                )}
            </g>
          );
        })}
        <line x1={left} x2={W - right} y1={base} y2={base} stroke="#4E4B46" />
        {Array.from(
          { length: Math.floor(L / (phone ? 500 : 250)) + 1 },
          (_, i) => i * (phone ? 500 : 250),
        ).map((d) => (
          <text
            key={d}
            x={X(start + d)}
            y={base + 16}
            textAnchor="middle"
            fill="#6A6660"
          >
            {d === 0
              ? "0"
              : (d / 1000).toFixed(d % 1000 ? 2 : 1).replace(/0$/, "")}
            {d + (phone ? 500 : 250) > L ? " km" : ""}
          </text>
        ))}
        <text
          x={X(start + L)}
          y={Y(max) - 8}
          textAnchor="end"
          fill="#F1EEE8"
          fontWeight="600"
        >
          {Math.round(gain)} m
        </text>
        {relative !== null && e !== null && (
          <g>
            <line
              x1={X(relative)}
              x2={X(relative)}
              y1={top - 6}
              y2={base}
              stroke="#5592E2"
              strokeOpacity=".85"
            />
            <circle
              cx={X(relative)}
              cy={Y(e)}
              r="3.5"
              fill="#5592E2"
              stroke="#0F0E0C"
              strokeWidth="1.5"
            />
            <text
              x={Math.min(W - (phone ? 160 : 210), X(relative) + 8)}
              y={top + 6}
              fill="#F1EEE8"
            >
              <tspan fontWeight="600">
                {((relative - start) / 1000).toFixed(2)} km
              </tspan>
              <tspan dx="7" fill="#9A9488">
                {Math.round(e - min)} m
              </tspan>
              <tspan dx="7" fill="#9A9488">
                {(
                  ((elevationAt(profile, Math.min(start + L, relative + 25)) -
                    elevationAt(profile, Math.max(start, relative - 25))) /
                    (Math.min(start + L, relative + 25) -
                      Math.max(start, relative - 25))) *
                  100
                ).toFixed(1)}
                %
              </tspan>
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}
