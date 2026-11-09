import "@/styles/climb-page.css";
import "@/styles/account-page.css";
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
import type { AccountPageData } from "@/types";
const empty: AccountPageData = {
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
  data = empty,
}: {
  pubkey: string;
  data?: AccountPageData;
}) {
  const completions = useRef<HTMLDialogElement>(null),
    settlements = useRef<HTMLDialogElement>(null);
  const completionRows = (all = false) =>
    data.completions
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
    data.settlements
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
    <div className="account-page" data-page-loaded="true">
      <div className="account-ground">
        <ObservatoryGround climbs={data.ground} mode="account" />
      </div>
      <section className="account-identity" aria-label="Rider">
        <div className="account-who">
          <span className="account-avatar">
            {data.handle && data.avatar_url ? (
              <img src={data.avatar_url} alt="" />
            ) : (
              (data.handle ?? pubkey).replace("@", "").slice(0, 2).toUpperCase()
            )}
          </span>
          <h1 className={data.handle ? "" : "mono-inline"}>
            {data.handle ?? shortenAddress(pubkey, 4).replace("...", "…")}
          </h1>
        </div>
        <button
          className="account-wallet"
          title="Wallet"
          onClick={() => void navigator.clipboard.writeText(pubkey)}
        >
          {pubkey}
        </button>
        {data.since_week ? (
          <div className="account-since">
            Since <b>Week {data.since_week}</b>
            {data.since_date
              ? ` · ${new Date(data.since_date).toLocaleDateString("en-US", { month: "short", year: "numeric" })}`
              : null}
          </div>
        ) : null}
        <div className="account-trio">
          {(
            [
              ["Rides attested", data.rides_attested],
              ["Seats", data.seats],
              ["Crowns", data.crowns],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              {value ? <b>{value}</b> : null}
            </div>
          ))}
        </div>
        <h2 className="page-eyebrow">Positions</h2>
        {data.positions.map((p) => (
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
        {data.attested_climbs && data.canon_count ? (
          <div className="account-coverage">
            {data.attested_climbs} of {data.canon_count} climbs attested
          </div>
        ) : null}
      </section>
      <div className="account-below">
        <div>
          <section>
            <h2 className="page-eyebrow">Balances</h2>
            <div className="page-surface">
              {data.balances.map((b) => (
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
            <h2 className="page-eyebrow">
              Completions
              {data.completion_count ? (
                <span>{data.completion_count}</span>
              ) : null}
            </h2>
            <div className="page-surface">
              {completionRows()}
              {data.completion_count ? (
                <button
                  className="page-door"
                  onClick={() => completions.current?.showModal()}
                >
                  All completions · {data.completion_count}
                  <span>›</span>
                </button>
              ) : null}
            </div>
          </section>
        </div>
        <div>
          <section>
            <h2 className="page-eyebrow">
              Settlements
              {data.settlement_count ? (
                <span>{data.settlement_count}</span>
              ) : null}
            </h2>
            <div className="page-surface">
              {settlementRows()}
              {data.settlement_count ? (
                <button
                  className="page-door"
                  onClick={() => settlements.current?.showModal()}
                >
                  All settlements · {data.settlement_count}
                  <span>›</span>
                </button>
              ) : null}
            </div>
          </section>
          <section>
            <h2 className="page-eyebrow">Activity</h2>
            <div className="page-surface">
              {data.activity.map((e) => (
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
        <IndexedStamp indexed={data.indexed} />
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
      <AccountPageContent pubkey={pubkey} data={q.data?.room} />
    </>
  );
}
