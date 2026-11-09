import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import GeographicCredit from "@/components/GeographicCredit";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { composeBrowserTitle } from "../../../portal/server/browser-title";
import { getClimb } from "@/lib/api";
import { formatAtomic, formatDuration, shortenAddress } from "@/lib/format";
import { LedgerRow, LedgerKv } from "@/components/ExplorerPrimitives";
import { ErrorState } from "@/components/PageStates";
import { IndexedStamp } from "@/components/FreshnessStamp";
import ObservatoryGround from "@/components/ground/ObservatoryGround";
import ClimbSection, {
  ClimbGlyph,
  validProfile,
} from "@/components/ground/ClimbSection";
import RankMark from "@/components/RankMark";
import ExplorerDialog from "@/components/ExplorerDialog";
import { useExpandableSheet } from "@/components/ExpandableSheet";
import type {
  ClimbResponse,
  ClimbRider,
  ClimbCompletion,
  ClimbSettlement,
  GroundClimb,
} from "@/types";
import "@/styles/climb-page.css";
const count = (n: number | undefined) =>
  n && n > 0 ? n.toLocaleString("en-US") : null;
const positive = (n: unknown) =>
  n != null && n !== "" && Number.isFinite(Number(n)) && Number(n) > 0;
const money = (n: string | undefined, unit: "CAL" | "DUNG") =>
  positive(n) ? formatAtomic(n, unit) : null;
const compact = (value: string, chars = 4) => shortenAddress(value, chars, "…");
const rider = (r: ClimbRider) => r.handle || compact(r.wallet);
const initials = (r: ClimbRider) =>
  (r.handle || r.wallet).replace(/^@/, "").slice(0, 2).toUpperCase();
const date = (value: string | undefined, long = false) =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value)
        .toLocaleDateString("en-US", {
          ...(long
            ? { year: "numeric" as const }
            : { weekday: "short" as const }),
          month: "short",
          day: "numeric",
          timeZone: "UTC",
        })
        .replace(long ? "" : /,/g, "")
    : null;
function Section({
  name,
  number,
  children,
  actions,
  id,
  onOpen,
}: {
  name: string;
  number?: number;
  children: ReactNode;
  actions?: ReactNode;
  id?: string;
  onOpen?: (trigger: HTMLElement) => void;
}) {
  return (
    <section data-climb-section={id}>
      <header className="climb-eyebrow">
        <h2>
          {onOpen ? (
            <button onClick={(e) => onOpen(e.currentTarget)}>{name}</button>
          ) : (
            name
          )}
        </h2>
        {actions ?? <span>{count(number)}</span>}
      </header>
      <div className="climb-ledger-sheet">{children}</div>
    </section>
  );
}
function CompletionRow({ row }: { row: ClimbCompletion }) {
  return (
    <LedgerRow
      data-ledger-row
      to={`/tx/${row.signature}`}
      mark={<span className="climb-avatar">{initials(row)}</span>}
      name={rider(row)}
      detail={["Ride attested", date(row.date), compact(row.signature, 6)]
        .filter(Boolean)
        .join(" · ")}
      value={positive(row.time_s) ? formatDuration(row.time_s) : null}
    />
  );
}
function SettlementRow({ row }: { row: ClimbSettlement }) {
  const amount = positive(row.dung)
    ? formatAtomic(row.dung, "DUNG", 9, 2)
    : null;
  return (
    <LedgerKv
      data-ledger-row
      label={[`Week ${row.week}`, date(row.date)].filter(Boolean).join(" · ")}
      to={`/tx/${row.signature}`}
    >
      {amount ? `+${amount}` : null}
    </LedgerKv>
  );
}

export default function VaultPage() {
  const { id = "" } = useParams();
  const result = useQuery({
    queryKey: ["climb", id],
    queryFn: () => getClimb(id),
    enabled: Boolean(id),
    refetchInterval: 60000,
  });
  useEffect(() => {
    document.title = composeBrowserTitle(
      result.data?.climb.name ?? null,
      "Climb",
      "BoulderScan",
    );
    return () => {
      document.title = "BoulderScan";
    };
  }, [result.data?.climb.name]);
  // A pending or failed read has no fabricated canon, money or replacement sentence.
  if (!result.data)
    return (
      <div
        className="climb-page"
        aria-busy={result.isLoading}
        data-page-loaded="false"
        data-page-state={result.isError ? "error" : "loading"}
      >
        {result.isError && <ErrorState title="Climb" onRetry={() => void result.refetch()} />}
      </div>
    );
  return <ClimbPageContent key={id} data={result.data} id={id} />;
}
export function ClimbPageContent({
  data,
  id,
}: {
  data: ClimbResponse;
  id: string;
}) {
  const { climb } = data,
    registration = data.registration ?? {};
  const profile = climb.canonical_profile ?? [],
    hasProfile = validProfile(profile);
  const [distance, setDistance] = useState<number | null>(() =>
      hasProfile
        ? profile[0].dist_m +
          (profile.at(-1)!.dist_m - profile[0].dist_m) * 0.55
        : null,
    ),
    [groundHeight, setGroundHeight] = useState(720);
  const [size, setSize] = useState({ width: 1440, height: 782, identity: 210 });
  const page = useRef<HTMLDivElement>(null),
    identity = useRef<HTMLElement>(null),
    desktopDrag = useRef<{ y: number; height: number } | null>(null);
  const { sheet, expanded, grip } = useExpandableSheet("reading");
  const phone = size.width < 700;
  const sheetHeight =
    sheet === "collapsed" ? 150 : size.height * (sheet === "max" ? 0.72 : 0.58);
  const fitBox = useMemo(
    () =>
      phone
        ? {
            left: 34,
            right: 34,
            top: 16 + size.identity + 30,
            bottom: sheetHeight + 22,
          }
        : {
            left: size.width >= 1000 ? 470 : 40,
            right: 70,
            top: 70,
            bottom: 120,
          },
    [phone, size.width, size.identity, sheetHeight],
  );
  useEffect(() => {
    const measure = () => {
      if (page.current)
        setSize({
          width: page.current.clientWidth,
          height:
            window.innerHeight -
            (document.querySelector(".week-shell__header")?.clientHeight ?? 62),
          identity: identity.current?.offsetHeight ?? 210,
        });
    };
    const observer = new ResizeObserver(measure);
    if (page.current) observer.observe(page.current);
    if (identity.current) observer.observe(identity.current);
    window.addEventListener("resize", measure);
    measure();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  const grounds = useMemo<GroundClimb[]>(
    () =>
      data.geometry
        ? [{ id, name: climb.name ?? "", geometry: data.geometry }]
        : [],
    [id, climb.name, data.geometry],
  );
  const fraction =
    distance === null || !hasProfile
      ? null
      : (distance - profile[0].dist_m) /
        (profile.at(-1)!.dist_m - profile[0].dist_m);
  const board = data.room_leaderboard ?? [],
    [boardMode, setBoardMode] = useState<"Time" | "Power">("Time");
  const completions = data.completions ?? [],
    positions = data.positions ?? [],
    settlements = data.settlements ?? [];
  const dialog = useRef<HTMLDialogElement>(null),
    returnFocus = useRef<HTMLElement | null>(null),
    [dialogName, setDialogName] = useState<string | null>(null);
  const open = (name: string, trigger: HTMLElement) => {
    returnFocus.current = trigger;
    setDialogName(name);
  };
  const close = () => {
    dialog.current?.close();
    setDialogName(null);
    returnFocus.current?.focus();
  };
  useEffect(() => {
    if (dialogName) dialog.current?.showModal();
  }, [dialogName]);
  const boardRows = board
    .filter((r) => boardMode === "Time" || positive(r.power_w))
    .map((r, i) => (
      <LedgerRow
        className={i >= 5 ? "climb-phone-extra" : ""}
        key={`${r.wallet}-${r.position ?? r.rank}`}
        to={`/account/${r.wallet}`}
        mark={<RankMark rank={r.rank} />}
        name={rider(r)}
        detail={date(r.date)}
        value={
          boardMode === "Time" ? formatDuration(r.time_s) : `${r.power_w} W`
        }
      />
    ));
  const legend = data.room_legend;
  const legendRow = legend ? (
    <LedgerRow
      to={`/account/${legend.wallet}`}
      mark={<span className="climb-avatar">{initials(legend)}</span>}
      name={rider(legend)}
      detail={`Legend of ${climb.name}`}
      value={
        <>
          {count(legend.completions)}
          <small>Completions</small>
        </>
      }
    />
  ) : null;
  const regLine = [
    positive(registration.week) ? `Registered Week ${registration.week}` : null,
    positive(registration.climb_number)
      ? `Climb #${registration.climb_number}`
      : null,
    positive(registration.canon_version)
      ? `canon v${registration.canon_version}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const ledger = (
    <div className="climb-ledger">
      <div className="climb-ledger-column">
        <Section
          name="Leaderboard"
          onOpen={(e) => open("Leaderboard", e)}
          actions={
            <span className="climb-words">
              {(["Time", "Power"] as const).map((mode) => (
                <button
                  key={mode}
                  aria-pressed={boardMode === mode}
                  onClick={() => setBoardMode(mode)}
                >
                  {mode}
                </button>
              ))}
            </span>
          }
        >
          {boardRows}
        </Section>
        <Section
          name="Local Legend"
          onOpen={legend ? (e) => open("Local Legend", e) : undefined}
        >
          {legendRow}
        </Section>
        <Section
          name="Completions"
          id="completions"
          number={data.completion_count}
        >
          {completions.slice(0, 3).map((r, i) => (
            <div
              className={i === 2 ? "climb-phone-extra" : ""}
              key={`${r.signature}-${r.event_index}`}
            >
              <CompletionRow row={r} />
            </div>
          ))}
          {positive(data.completion_count) && (
            <button
              className="week-kv ledger-kv climb-all"
              onClick={(e) => open("Completions", e.currentTarget)}
            >
              <span>All completions</span>
              <b>
                {count(data.completion_count)} <span aria-hidden="true">›</span>
              </b>
            </button>
          )}
        </Section>
      </div>
      <div className="climb-ledger-column">
        <Section
          name="Positions"
          onOpen={positions.length ? (e) => open("Positions", e) : undefined}
          id="positions"
          number={data.position_count}
        >
          {(money(data.deposited, "CAL") ||
            money(data.leaderboard_pool, "DUNG")) && (
            <div className="climb-numeral">
              {money(data.deposited, "CAL") && (
                <b data-climb-figure="deposited">
                  {money(data.deposited, "CAL")}
                </b>
              )}
              <span>
                {money(data.deposited, "CAL") ? "deposited" : null}
                {money(data.deposited, "CAL") &&
                money(data.leaderboard_pool, "DUNG")
                  ? " · "
                  : null}
                {money(data.leaderboard_pool, "DUNG") && (
                  <span data-climb-figure="leaderboard_pool">
                    Leaderboard pool {money(data.leaderboard_pool, "DUNG")}
                  </span>
                )}
              </span>
            </div>
          )}
          {positions.map((r, i) => (
            <LedgerRow
              data-ledger-row
              key={r.wallet}
              className={i >= 2 ? "climb-phone-extra" : ""}
              to={`/account/${r.wallet}`}
              mark={<RankMark rank={r.rank} />}
              name={rider(r)}
              detail={[
                r.rank === 1 ? "Crown" : "Seat",
                r.since ? `since ${date(r.since, true)}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              value={money(r.cal, "CAL")}
            />
          ))}
        </Section>
        <Section name="Settlements" id="settlements">
          {settlements.slice(0, 3).map((r, i) => (
            <div
              className={i === 2 ? "climb-phone-extra" : ""}
              key={`${r.signature}-${r.event_index}`}
            >
              <SettlementRow row={r} />
            </div>
          ))}
          {positive(data.settlement_count) && (
            <button
              className="week-kv ledger-kv climb-all"
              onClick={(e) => open("Settlements", e.currentTarget)}
            >
              <span>All settlements</span>
              <b>
                {count(data.settlement_count)} <span aria-hidden="true">›</span>
              </b>
            </button>
          )}
        </Section>
        <Section name="Registration" id="registration">
          {registration.climb_account && (
            <LedgerKv
              data-registration-key="climb_account"
              label="Climb account"
              to={`/account/${registration.climb_account}`}
            >
              {compact(registration.climb_account)}
            </LedgerKv>
          )}
          {registration.vault_account && (
            <LedgerKv
              data-registration-key="vault_account"
              label="Vault account"
              to={`/account/${registration.vault_account}`}
            >
              {compact(registration.vault_account)}
            </LedgerKv>
          )}
          {registration.signature && (
            <LedgerKv
              data-registration-key="signature"
              label="Registered"
              to={`/tx/${registration.signature}`}
            >
              {[
                positive(registration.week)
                  ? `Week ${registration.week}`
                  : null,
                compact(registration.signature, 6),
              ]
                .filter(Boolean)
                .join(" · ")}
            </LedgerKv>
          )}
          {positive(registration.canon_version) && (
            <LedgerKv data-registration-key="canon_version" label="Canon">
              v{registration.canon_version}
              {positive(registration.point_count)
                ? ` · ${registration.point_count} points`
                : null}
            </LedgerKv>
          )}
        </Section>
      </div>
    </div>
  );
  return (
    <div
      ref={page}
      className="climb-page"
      data-page-loaded="true"
      data-sheet={expanded ? "reading" : "looking"}
      style={
        {
          "--climb-ground-height": `${groundHeight}px`,
          "--climb-sheet-height": `${sheetHeight}px`,
        } as CSSProperties
      }
    >
      <div className="climb-ground">
        <ObservatoryGround
          climbs={grounds}
          mode="climb"
          fitBox={fitBox}
          fraction={fraction}
        />
        <header ref={identity} className="climb-identity" data-climb-identity>
          <div className="climb-id-row">
            {hasProfile && (
              <div className="climb-glyph">
                <ClimbGlyph profile={profile} />
              </div>
            )}
            <div>
              <h1>{climb.name}</h1>
              {data.place && <div className="climb-place">{data.place}</div>}
            </div>
          </div>
          <dl className="climb-trio">
            {positive(climb.length_m) && (
              <div>
                <dt>Distance</dt>
                <dd>
                  {Number(climb.length_m) >= 1000
                    ? `${(Number(climb.length_m) / 1000).toFixed(1)} km`
                    : `${Math.round(Number(climb.length_m))} m`}
                </dd>
              </div>
            )}
            {positive(climb.elev_gain_m) && (
              <div>
                <dt>Elevation</dt>
                <dd>{Math.round(Number(climb.elev_gain_m))} m</dd>
              </div>
            )}
            {positive(climb.avg_gradient_pct) && (
              <div>
                <dt>Grade</dt>
                <dd>{Number(climb.avg_gradient_pct).toFixed(1)}%</dd>
              </div>
            )}
          </dl>
          {regLine && <div className="climb-registered">
            {positive(registration.week) && <>Registered <b>Week {registration.week}</b></>}
            {positive(registration.climb_number) && <>{positive(registration.week) ? ' · ' : ''}Climb #{registration.climb_number}</>}
            {positive(registration.canon_version) && <>{positive(registration.week) || positive(registration.climb_number) ? ' · ' : ''}canon v{registration.canon_version}</>}
          </div>}
        </header>
        <div className="climb-ground-fade" />
        <div className="observatory-attribution">
          <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>{" "}
          <a href="https://openmaptiles.org/">© OpenMapTiles</a>{" "}
          <a href="https://carto.com/attributions">© CARTO</a>{" "}
          <a href="https://registry.opendata.aws/terrain-tiles/">Terrain: Mapzen (AWS)</a>{" "}
          <a href="https://docs.boulderroller.xyz/open-data">Data and sources</a>
        </div>
      </div>
      <div className="climb-page-sheet">
        <div className="climb-grip">
          <button
            className="climb-seam"
            aria-label="Climb sheet"
            aria-expanded={expanded}
            aria-controls="climb-ledger-scroll"
            {...(phone
              ? grip
              : {
                  onPointerDown: (e) => {
                    desktopDrag.current = {
                      y: e.clientY,
                      height: groundHeight,
                    };
                    e.currentTarget.setPointerCapture(e.pointerId);
                  },
                  onPointerMove: (e) => {
                    if (desktopDrag.current)
                      setGroundHeight(
                        Math.max(
                          320,
                          Math.min(
                            1040,
                            desktopDrag.current.height +
                              e.clientY -
                              desktopDrag.current.y,
                          ),
                        ),
                      );
                  },
                  onPointerUp: () => {
                    desktopDrag.current = null;
                  },
                  onPointerCancel: () => {
                    desktopDrag.current = null;
                  },
                  onClick: () => {},
                  onKeyDown: (e) => {
                    if (
                      ["ArrowUp", "ArrowDown", "Home", "End"].includes(e.key)
                    ) {
                      e.preventDefault();
                      setGroundHeight(
                        e.key === "Home"
                          ? 320
                          : e.key === "End"
                            ? 1040
                            : Math.max(
                                320,
                                Math.min(
                                  1040,
                                  groundHeight +
                                    (e.key === "ArrowUp" ? -80 : 80),
                                ),
                              ),
                      );
                    }
                  },
                })}
          >
            <i />
          </button>
          <GeographicCredit climb={climb} />
          <ClimbSection
            profile={profile}
            name={climb.name ?? ""}
            distance={distance}
            onInspect={setDistance}
          />
        </div>
        <div id="climb-ledger-scroll" className="climb-ledger-scroll">
          {ledger}
          <IndexedStamp indexed={data.indexed} />
        </div>
      </div>
      <ExplorerDialog
        ref={dialog}
        aria-label={dialogName ?? undefined}
        onCancel={(e) => {
          e.preventDefault();
          close();
        }}
        className="climb-detail-sheet"
      >
        <div className="observatory-search-bar">
          <b>{dialogName}</b>
          <button onClick={close}>Done</button>
        </div>
        <div className="climb-dialog-rows">
          {dialogName === "Leaderboard"
            ? boardRows
            : dialogName === "Local Legend"
              ? legendRow
              : dialogName === "Completions"
                ? completions.map((r) => (
                    <CompletionRow
                      key={`${r.signature}-${r.event_index}`}
                      row={r}
                    />
                  ))
                : dialogName === "Settlements"
                  ? settlements.map((r) => (
                      <SettlementRow
                        key={`${r.signature}-${r.event_index}`}
                        row={r}
                      />
                    ))
                  : dialogName === "Positions"
                    ? positions.map((r) => (
                        <LedgerRow
                          key={r.wallet}
                          to={`/account/${r.wallet}`}
                          mark={<RankMark rank={r.rank} />}
                          name={rider(r)}
                          value={money(r.cal, "CAL")}
                        />
                      ))
                    : null}
        </div>
      </ExplorerDialog>
    </div>
  );
}
