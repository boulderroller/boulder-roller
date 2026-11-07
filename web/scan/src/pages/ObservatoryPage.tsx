import {LedgerRow} from '@/components/ExplorerPrimitives';
import {useRoomSheet} from '@/components/RoomSheet';
import {IndexedStamp} from '@/components/FreshnessStamp';
import { useCallback, useEffect, useRef, useState } from "react";
import { composeBrowserTitle } from "../../../portal/server/browser-title";
import { Link } from "react-router-dom";
import { useInfiniteQuery } from "@tanstack/react-query";
import { getObservatory } from "@/lib/api";
import { formatAtomic, formatDuration } from "@/lib/format";
import ObservatoryGround from "@/components/ground/ObservatoryGround";
import ObservatorySearch from "@/components/ObservatorySearch";
import type { GroundClimb, RoomEvent, WeekProjection } from "@/types";

const EMPTY_CLIMBS: GroundClimb[] = [];
const words = {
  settlement: "DUNG distributed",
  attestation: "Ride attested",
  deposit: "CAL deposited",
  legend: "Local Legend",
  registration: "Climb registered",
};
const glyphs = {
  settlement: "◆",
  attestation: "✓",
  deposit: "▲",
  legend: "☆",
  registration: "■",
};
const compact = (s: string) =>
  s.length > 24 ? `${s.slice(0, 6)}…${s.slice(-6)}` : s;
const count = (n: number) => n.toLocaleString("en-US");
export function weekRows(week: WeekProjection) {
  return [
    [
      "climbs_registered",
      "Climbs registered",
      week.climbs_registered ? count(week.climbs_registered) : null,
    ],
    [
      "cal_deposited",
      "CAL deposited",
      week.cal_deposited && BigInt(week.cal_deposited) > 0n
        ? formatAtomic(week.cal_deposited, "CAL")
        : null,
    ],
    ["riders", "Riders", week.riders ? count(week.riders) : null],
    [
      "rides_attested",
      "Rides attested",
      week.rides_attested ? `${count(week.rides_attested)} this week` : null,
    ],
    [
      "dung_distributed",
      "DUNG distributed",
      week.dung_distributed && BigInt(week.dung_distributed) > 0n
        ? `${formatAtomic(week.dung_distributed, "DUNG")} last week`
        : null,
    ],
  ].filter((row): row is string[] => Boolean(row[2]));
}
function eventTime(value: RoomEvent["block_time"]) {
  if (value == null) return undefined;
  const d = new Date(
    typeof value === "number" || /^\d+$/.test(value)
      ? Number(value) * 1000
      : value,
  );
  if (!Number.isFinite(d.getTime())) return undefined;
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
  if (seconds >= 0 && seconds < 60) return `${seconds}s`;
  if (seconds >= 60 && seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds >= 3600 && seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    ...(seconds >= 0 && seconds < 604800 ? {} : {month: "short" as const, day: "numeric" as const}),
    timeZone: "UTC",
  }).replaceAll(",", "");
}
function valueText(event: RoomEvent) {
  if (!event.value) return null;
  const { amount, unit } = event.value;
  if (unit === "CAL" || unit === "DUNG") {
    let number = formatAtomic(amount);
    if (event.kind === "settlement" && /^[\d,]+(?:\.\d+)?$/.test(number)) {
      const [whole, fraction = ""] = number.split(".");
      number = `${whole}.${fraction.padEnd(2, "0")}`;
    }
    return `${event.kind === "settlement" ? "+" : ""}${number} ${unit}`;
  }
  if (unit === "seconds") return formatDuration(amount);
  if (unit === "meters") return `${(Number(amount) / 1000).toFixed(1)} km`;
  return `${amount} ${unit}`;
}
export function RecentRow({ event }: { event: RoomEvent }) {
  if (!event.kind || !event.object || !event.signature) return null;
  return (
    <LedgerRow to={`/tx/${event.signature}`} data-event-kind={event.kind}
      mark={glyphs[event.kind]} name={event.object.type === 'rider' ? compact(event.object.name) : event.object.name}
      detail={[event.kind === 'settlement' && event.epoch != null ? `Week ${event.epoch} settled` : words[event.kind], event.actor ? compact(event.actor) : null, eventTime(event.block_time)].filter(Boolean).join(' · ')}
      value={valueText(event)} />
  );
}
export default function ObservatoryPage() {
  const result = useInfiniteQuery({
    queryKey: ["observatory-room"],
    queryFn: ({ pageParam }) => getObservatory(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => last.events_next_offset ?? undefined,
    refetchInterval: 60000,
  });
  const data = result.data?.pages[0],
    week = data?.week ?? {};
  const climbs = data?.climbs ?? EMPTY_CLIMBS;
  const [chosen, setChosen] = useState<GroundClimb | null>(null);
  const {sheet, expanded, grip} = useRoomSheet();
  const end = useRef<HTMLDivElement>(null);
  const choose = useCallback((c: GroundClimb) => setChosen(c), []);
  const selected = chosen
    ? climbs.find((c) => c.id === chosen.id)
    : climbs.reduce<GroundClimb | undefined>(
        (best, c) =>
          c.deposited && BigInt(c.deposited) > BigInt(best?.deposited ?? "0")
            ? c
            : best,
        undefined,
      );
  const title = week.epoch != null ? `Week ${week.epoch}` : null;
  const settle = week.settles_at
    ? `settles ${new Date(week.settles_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }).replaceAll(",", "")}`
    : null;
  useEffect(() => {
    document.title = title ? composeBrowserTitle(null, title, "BoulderScan") : "BoulderScan";
    return () => {
      document.title = "BoulderScan";
    };
  }, [title]);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries.some((e) => e.isIntersecting) &&
          result.hasNextPage &&
          !result.isFetchingNextPage &&
          !result.isFetchNextPageError
        )
          void result.fetchNextPage();
      },
      { threshold: 0.1 },
    );
    if (end.current) observer.observe(end.current);
    return () => observer.disconnect();
  }, [
    result.hasNextPage,
    result.isFetchingNextPage,
    result.isFetchNextPageError,
    result.fetchNextPage,
    expanded,
  ]);
  const seen = new Set<string>();
  const events = (
    result.data?.pages.flatMap((p) => p.recent_events) ?? []
  ).filter((e) => {
    const id = `${e.tx_signature}:${e.event_index}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  return (
    <div
      className="observatory-room"
      data-room-loaded={Boolean(data)}
      aria-busy={result.isLoading}
    >
      <ObservatoryGround climbs={climbs} onChoose={choose} />
      <aside
        className={`week-column ${expanded ? "is-expanded" : ""} ${sheet === "max" ? "is-max" : ""}`}
        aria-label="Week"
      >
        <button
          className="week-phone-head"
          aria-label={title ?? "Week"}
          aria-expanded={expanded}
          aria-controls="week-ledger"
          {...grip}
        >
          <i />
          <span>
            <b>{title}</b>
            <small>{settle}</small>
          </span>
        </button>
        <div className="week-desktop-head">
          <h1>
            {title}
            <small>{settle}</small>
          </h1>
        </div>
        <div id="week-ledger" className="week-ledger">
          <div className="week-ledger-content">
          <dl className="week-figures">
            {weekRows(week).map(([key, label, value]) => (
              <div className="week-kv" data-week-key={key} key={key}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <h2 className="week-recent">Recent</h2>
          <div className="week-events">
            {events.map((e) => (
              <RecentRow key={`${e.tx_signature}:${e.event_index}`} event={e} />
            ))}
            <div ref={end} className="week-events-end" />
          </div>
          </div>
          <IndexedStamp indexed={data?.indexed} />
        </div>
      </aside>
      <ObservatorySearch climbs={climbs} />
      {selected ? (
        <Link className="observatory-card" to={`/climb/${selected.id}`}>
          <div>
            <b>{selected.name}</b>
            <span>
              {[
                selected.length_m
                  ? `${(selected.length_m / 1000).toFixed(1)} km`
                  : null,
                selected.elev_gain_m
                  ? `${Math.round(selected.elev_gain_m)} m`
                  : null,
                selected.avg_gradient_pct
                  ? `${selected.avg_gradient_pct.toFixed(1)}%`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              {selected.completions ? (
                <span className="observatory-card-completions">
                  {" "}
                  · {selected.completions} completions
                </span>
              ) : null}
            </span>
          </div>
          {selected.deposited ? (
            <em>{formatAtomic(selected.deposited, "CAL")}</em>
          ) : null}
          <i aria-hidden="true">›</i>
        </Link>
      ) : null}
      {data?.program_id ? (
        <div className="observatory-program">
          Program {compact(data.program_id)}
        </div>
      ) : null}
      <div className="observatory-attribution">
        <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>{" "}
        <a href="https://openmaptiles.org/">© OpenMapTiles</a>{" "}
        <a href="https://carto.com/attributions">© CARTO</a>{" "}
          <a href="https://registry.opendata.aws/terrain-tiles/">Terrain: Mapzen (AWS)</a>{" "}
          <a href="https://docs.boulderroller.xyz/open-data">Data and sources</a>
      </div>
    </div>
  );
}
