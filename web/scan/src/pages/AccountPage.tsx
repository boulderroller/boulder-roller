import "@/styles/climb-room.css";
import "@/styles/account-room.css";
import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { composeBrowserTitle } from "../../../portal/server/browser-title";
import { getAccount } from "@/lib/api";
import { formatAtomic, formatDuration, shortenAddress } from "@/lib/format";
import ObservatoryGround from "@/components/ground/ObservatoryGround";
import RankMark from "@/components/RankMark";
import { LedgerKv, LedgerRow } from "@/components/ExplorerPrimitives";
import ExplorerDialog from "@/components/ExplorerDialog";

import { IndexedStamp } from "@/components/FreshnessStamp";
import { ErrorState } from "@/components/PageStates";
import type { AccountRoom } from "@/types";
const empty: AccountRoom = {
  ground: [],
  positions: [],
  balances: [],
  completions: [],
  settlements: [],
  activity: [],
};
const date = (s?: string) =>
  s && Number.isFinite(Date.parse(s))
    ? new Date(s).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric", timeZone:"UTC",
      })
    : undefined;
const rank = (n?: number) =>
  n === 1 ? "Crown" : n && n <= 10 ? "Seat" : undefined;
export function AccountPageContent({
  pubkey,
  room = empty,
}: {
  pubkey: string;
  room?: AccountRoom;
}) {
  const completions = useRef<HTMLDialogElement>(null),
    settlements = useRef<HTMLDialogElement>(null);
  const completionRows = (all = false) =>
    room.completions
      .slice(0, all ? undefined : 3)
      .map((r, i) => (
        <LedgerRow
          key={`${r.signature}-${r.event_index ?? i}`}
          to={`/tx/${r.signature}`}
          name={r.climb.name}
          detail={[
            "Ride attested",
            date(r.date),
            shortenAddress(r.signature, 6),
          ]
            .filter(Boolean)
            .join(" · ")}
          value={r.time_s ? formatDuration(r.time_s) : undefined}
        />
      ));
  const settlementRows = (all = false) =>
    room.settlements
      .slice(0, all ? undefined : 3)
      .map((r, i) => (
        <LedgerRow
          key={`${r.signature}-${r.event_index ?? i}`}
          to={`/tx/${r.signature}`}
          name={r.climb.name}
          detail={[
            r.week ? `Week ${r.week}` : undefined,
            date(r.date),
            rank(r.rank),
          ]
            .filter(Boolean)
            .join(" · ")}
          value={r.dung ? `+${formatAtomic(r.dung, "DUNG")}` : undefined}
        />
      ));
  return (
    <div className="account-room" data-room-loaded="true">
      <div className="account-ground">
        <ObservatoryGround climbs={room.ground} mode="account" />
      </div>
      <section className="account-identity" aria-label="Rider">
        <div className="account-who">
          <span className="account-avatar">
            {room.handle && room.avatar_url ? (
              <img src={room.avatar_url} alt="" />
            ) : (
              (room.handle ?? pubkey).replace("@", "").slice(0, 2).toUpperCase()
            )}
          </span>
          <h1 className={room.handle ? "" : "mono-inline"}>
            {room.handle ?? shortenAddress(pubkey, 4).replace("...", "…")}
          </h1>
        </div>
        <button
          className="account-wallet"
          title="Wallet"
          onClick={() => void navigator.clipboard.writeText(pubkey)}
        >
          {pubkey}
        </button>
        {room.since_week ? (
          <div className="account-since">
            Since <b>Week {room.since_week}</b>
            {room.since_date
              ? ` · ${new Date(room.since_date).toLocaleDateString("en-US", { month: "short", year: "numeric" })}`
              : null}
          </div>
        ) : null}
        <div className="account-trio">
          {(
            [
              ["Rides attested", room.rides_attested],
              ["Seats", room.seats],
              ["Crowns", room.crowns],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              {value ? <b>{value}</b> : null}
            </div>
          ))}
        </div>
        <h2 className="room-eyebrow">Positions</h2>
        {room.positions.map((p) => (
          <LedgerRow
            key={p.climb.id}
            to={`/climb/${p.climb.id}`}
            mark={<RankMark rank={p.rank} />}
            name={p.climb.name}
            detail={[
              rank(p.rank),
              p.since ? `since ${date(p.since)}` : undefined,
            ]
              .filter(Boolean)
              .join(" · ")}
            value={p.cal ? formatAtomic(p.cal, "CAL") : undefined}
          />
        ))}
        {room.attested_climbs && room.canon_count ? (
          <div className="account-census">
            {room.attested_climbs} of {room.canon_count} climbs attested
          </div>
        ) : null}
      </section>
      <div className="account-below">
        <div>
          <section>
            <h2 className="room-eyebrow">Balances</h2>
            <div className="room-surface">
              {room.balances.map((b) => (
                <LedgerKv
                  key={b.account}
                  label={
                    b.custody === "climb"
                      ? "CAL deposited on climbs"
                      : `${b.symbol} in wallet`
                  }
                >
                  {formatAtomic(b.amount, b.symbol)}
                </LedgerKv>
              ))}
              <LedgerKv label="Wallet" to={`/account/${pubkey}`}>
                {shortenAddress(pubkey,10)}
              </LedgerKv>
            </div>
          </section>
          <section>
            <h2 className="room-eyebrow">
              Completions
              {room.completion_count ? (
                <span>{room.completion_count}</span>
              ) : null}
            </h2>
            <div className="room-surface">
              {completionRows()}
              {room.completion_count ? (
                <button
                  className="room-door"
                  onClick={() => completions.current?.showModal()}
                >
                  All completions · {room.completion_count}
                  <span>›</span>
                </button>
              ) : null}
            </div>
          </section>
        </div>
        <div>
          <section>
            <h2 className="room-eyebrow">
              Settlements
              {room.settlement_count ? (
                <span>{room.settlement_count}</span>
              ) : null}
            </h2>
            <div className="room-surface">
              {settlementRows()}
              {room.settlement_count ? (
                <button
                  className="room-door"
                  onClick={() => settlements.current?.showModal()}
                >
                  All settlements · {room.settlement_count}
                  <span>›</span>
                </button>
              ) : null}
            </div>
          </section>
          <section>
            <h2 className="room-eyebrow">Activity</h2>
            <div className="room-surface">
              {room.activity.map((e) => (
                <LedgerRow
                  key={`${e.tx_signature}-${e.event_index}`}
                  to={`/tx/${e.signature}`}
                  name={
                    e.kind
                      ? {
                          attestation: "Ride attested",
                          settlement: "Settled",
                          deposit: "CAL deposited",
                          legend: "Local Legend",
                          registration: "Climb registered",
                        }[e.kind]
                      : undefined
                  }
                  detail={[
                    e.object?.name,
                    date(
                      e.block_time == null ? undefined : String(e.block_time),
                    ),
                    e.signature ? shortenAddress(e.signature, 6) : undefined,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  value={
                    e.value
                      ? e.value.unit === "seconds"
                        ? formatDuration(e.value.amount)
                        : formatAtomic(e.value.amount, e.value.unit)
                      : undefined
                  }
                />
              ))}
            </div>
          </section>
        </div>
        <IndexedStamp indexed={room.indexed} />
      </div>
      <ExplorerDialog ref={completions} aria-label="Completions">
        <h2>Completions</h2>
        <button aria-label="Close" onClick={() => completions.current?.close()}>
          ×
        </button>
        {completionRows(true)}
      </ExplorerDialog>
      <ExplorerDialog ref={settlements} aria-label="Settlements">
        <h2>Settlements</h2>
        <button aria-label="Close" onClick={() => settlements.current?.close()}>
          ×
        </button>
        {settlementRows(true)}
      </ExplorerDialog>
    </div>
  );
}
export default function AccountPage() {
  const { pubkey = "" } = useParams();
  const q = useQuery({
    queryKey: ["account", pubkey],
    queryFn: () => getAccount(pubkey),
    enabled: !!pubkey,
  });
  useEffect(() => {
    document.title = composeBrowserTitle(
      q.data?.room?.handle ?? shortenAddress(pubkey, 4).replace("...", "…"),
      "Rider",
      "BoulderScan",
    );
    return () => {
      document.title = "BoulderScan";
    };
  }, [pubkey, q.data?.room?.handle]);
  return (
    <>
      {q.isError ? (
        <ErrorState title="Account unavailable" onRetry={() => q.refetch()} />
      ) : null}
      <AccountPageContent pubkey={pubkey} room={q.data?.room} />
    </>
  );
}
