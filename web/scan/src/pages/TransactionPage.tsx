import "@/styles/climb-room.css";
import "@/styles/account-room.css";
import "@/styles/transaction-room.css";
import { useEffect, useRef, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { composeBrowserTitle } from "../../../portal/server/browser-title";
import { getTransaction } from "@/lib/api";
import {
  formatAtomic,
  formatCount,
  formatDuration,
  shortenAddress,
} from "@/lib/format";
import { LedgerKv } from "@/components/ExplorerPrimitives";
import ExplorerDialog from "@/components/ExplorerDialog";
import ObservatorySearch from "@/components/ObservatorySearch";
import { ErrorState } from "@/components/PageStates";
import type { TransactionResponse, TransactionReceipt } from "@/types";
const titles = {
  attestation: "Ride attested",
  settlement: "Settled",
  deposit: "CAL deposited",
  withdrawal: "CAL withdrawn",
  collection: "Collected",
  registration: "Climb registered",
  legend: "Local Legend",
};
const compact = (s: string) => shortenAddress(s, 6).replace("...", "…");
const date = (s: unknown, seconds = false) => {
  if (s == null || s === "") return undefined;
  const n = /^\d+$/.test(String(s)) ? Number(s) * 1000 : Date.parse(String(s)),
    d = new Date(n);
  if (!Number.isFinite(d.getTime())) return undefined;
  return `${d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).replace(",", "")} · ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" as const } : {}), timeZone: "UTC" })}`;
};
const weekRange = (f: TransactionReceipt["fields"]) =>
  f.week_starts_at && f.week_ends_at
    ? `${new Date(f.week_starts_at).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })} – ${new Date(f.week_ends_at).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}`
    : undefined;

function Sheet({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="room-eyebrow">{title}</h2>
      <div className="room-surface">{children}</div>
    </section>
  );
}
export function TransactionNotFound({ id }: { id: string }) {
  return (
    <div className="receipt-room">
      <div className="receipt-column">
        <h1>Transaction</h1>
        <div className="receipt-sub mono-inline" title={id}>{compact(id)}</div>
        <div className="room-surface receipt-not-found">
          <span>Not found</span>
          <ObservatorySearch climbs={[]} triggerLabel="Search ›" />
        </div>
      </div>
    </div>
  );
}
export function TransactionPageContent({
  data,
}: {
  data: TransactionResponse;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    r = data.receipt ?? { fields: {}, accounts: [] },
    f = r.fields;
  const title = r.kind ? titles[r.kind] : "Transaction",
    rider = r.rider?.handle ?? (r.rider ? compact(r.rider.wallet) : undefined);
  const climb = r.climb ? (
    <LedgerKv label="Climb" to={`/climb/${r.climb.id}`}>
      <span className="receipt-name">{r.climb.name}</span>
    </LedgerKv>
  ) : null;
  const who = r.rider ? (
    <LedgerKv
      label={
        r.kind === "deposit" || r.kind === "withdrawal" ? "Wallet" : "Rider"
      }
      to={`/account/${r.rider.wallet}`}
    >
      <span className={r.rider.handle ? "receipt-name" : undefined}>
        {rider}
      </span>
    </LedgerKv>
  ) : null;
  const kv = (label: string, value: ReactNode, to?: string) =>
    value == null || value === 0 || value === "" ? null : (
      <LedgerKv label={label} to={to}>
        {value}
      </LedgerKv>
    );
  return (
    <div className="receipt-room" data-room-loaded="true">
      <div className="receipt-column">
        {r.climb ? (
          <Link className="receipt-back" to={`/climb/${r.climb.id}`}>
            ‹ <b>{r.climb.name}</b> · Climb
          </Link>
        ) : r.rider ? (
          <Link className="receipt-back" to={`/account/${r.rider.wallet}`}>
            ‹ <b>{rider}</b> · Rider
          </Link>
        ) : f.week ? (
          <Link className="receipt-back" to="/">
            ‹ <b>Week {f.week}</b> · Week
          </Link>
        ) : null}
        <h1>{title}</h1>
        <div className="receipt-sub">
          {[
            r.climb?.name,
            rider ?? (f.week ? `Week ${f.week}` : undefined),
            date(data.block_time),
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
        {r.kind === "attestation" ? (
          <Sheet title="Ride">
            {climb}
            {who}
            {kv("Time", f.time_s ? formatDuration(f.time_s) : undefined)}
            {kv(
              "New best",
              f.previous_best_s ? (
                <span className="receipt-best">
                  was {formatDuration(f.previous_best_s)}
                </span>
              ) : undefined,
            )}
            {kv("Ride hash", f.ride_hash ? compact(f.ride_hash) : undefined)}
            {kv("Completed", date(f.completed))}
            {kv("Week", f.week)}
          </Sheet>
        ) : null}
        {r.kind === "settlement" ? (
          <>
            <Sheet title="Settlement">
              {climb}
              {kv(
                "Week",
                f.week
                  ? [f.week, weekRange(f)].filter(Boolean).join(" · ")
                  : undefined,
              )}
              {kv(
                "DUNG distributed",
                f.dung ? formatAtomic(f.dung, "DUNG") : undefined,
              )}
              {kv("Positions paid", f.positions_paid)}
              {kv("Completions counted", f.completions)}
            </Sheet>
            <Sheet title="Paid">
              {r.paid?.map((p, i) => (
                <LedgerKv
                  key={`${p.wallet}-${i}`}
                  label={[
                    p.handle ?? compact(p.wallet),
                    p.rank === 1
                      ? "Crown"
                      : p.rank && p.rank <= 10
                        ? "Seat"
                        : undefined,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  to={`/account/${p.wallet}`}
                >
                  {formatAtomic(p.dung, "DUNG")}
                </LedgerKv>
              ))}
            </Sheet>
          </>
        ) : null}
        {r.kind === "deposit" || r.kind === "withdrawal" ? (
          <Sheet title="Position">
            {climb}
            {who}
            {kv("CAL", f.cal ? formatAtomic(f.cal, "CAL") : undefined)}
            {kv("Rank after", f.rank)}
            {kv("Since", date(f.since))}
          </Sheet>
        ) : null}
        {r.kind === "collection" ? (
          <Sheet title="Collected">
            {climb}
            {who}
            {kv("DUNG", f.dung ? formatAtomic(f.dung, "DUNG") : undefined)}
          </Sheet>
        ) : null}
        {r.kind === "registration" ? (
          <Sheet title="Registration">
            {climb}
            {kv(
              "Canon",
              f.canon_version
                ? `v${f.canon_version}${f.point_count ? ` · ${f.point_count} points` : ""}`
                : undefined,
            )}
            {kv(
              "Climb account",
              f.climb_account ? compact(f.climb_account) : undefined,
              f.climb_account ? `/account/${f.climb_account}` : undefined,
            )}
            {kv(
              "Vault account",
              f.vault_account ? compact(f.vault_account) : undefined,
              f.vault_account ? `/account/${f.vault_account}` : undefined,
            )}
            {kv("Week", f.week)}
          </Sheet>
        ) : null}
        {r.kind === "legend" ? (
          <Sheet title="Local Legend">
            {climb}
            {who}
            {kv("Completions", f.completions)}
            {kv("Week", f.week)}
          </Sheet>
        ) : null}
        <Sheet title="On chain">
          <LedgerKv label="Signature">
            <button
              className="room-copy receipt-signature"
              title={data.signature}
              onClick={() => void navigator.clipboard.writeText(data.signature)}
            >
              {data.signature}
            </button>
          </LedgerKv>
          {kv(
            "Status",
            data.status === "success" ? (
              <span className="receipt-name">Success</span>
            ) : data.status === "failed" ? (
              <span className="receipt-name">Failed</span>
            ) : undefined,
          )}
          {kv(
            "Slot",
            data.slot != null && Number(data.slot) > 0
              ? formatCount(data.slot)
              : undefined,
          )}
          {kv("Block time", date(data.block_time, true))}
          {kv(
            "Fee",
            data.fee_lamports && /^\d+$/.test(data.fee_lamports)
              ? formatAtomic(data.fee_lamports, "SOL")
              : undefined,
          )}
          {kv(
            "Program",
            r.program ? compact(r.program) : undefined,
            r.program ? `/account/${r.program}` : undefined,
          )}
        </Sheet>
        <Sheet title="Accounts">
          {r.accounts.map((a, i) => (
            <LedgerKv
              key={`${a.role}-${a.pubkey}-${i}`}
              label={a.role ?? ""}
              to={`/account/${a.pubkey}`}
            >
              {compact(a.pubkey)}
            </LedgerKv>
          ))}
        </Sheet>
        <div className="room-surface receipt-doors">
          {data.instructions.length ? (
            <button
              className="room-door"
              onClick={() => dialog.current?.showModal()}
            >
              Instructions · {data.instructions.length}
              <span>›</span>
            </button>
          ) : null}
          <a
            className="room-door"
            href={`https://explorer.solana.com/tx/${encodeURIComponent(data.signature)}?cluster=devnet`}
            target="_blank"
            rel="noreferrer"
          >
            Solana Explorer<span>›</span>
          </a>
        </div>
        <ExplorerDialog
          ref={dialog}
          className="receipt-instructions"
          aria-label="Instructions"
        >
          <div className="observatory-search-bar">
            <b>Instructions</b>
            <button onClick={() => dialog.current?.close()}>Done</button>
          </div>
          {data.instructions.map((ix) => (
            <section key={ix.instruction_index}>
              <h2 className="room-eyebrow">{ix.name}</h2>
              {Object.entries(ix.args ?? {}).map(([name, value]) =>
                value != null ? (
                  <LedgerKv key={name} label={name}>
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </LedgerKv>
                ) : null,
              )}
              {Object.entries(ix.accounts ?? {}).map(([name, value]) => (
                <LedgerKv key={name} label={name}>
                  {typeof value === "string" ? value : value.pubkey}
                </LedgerKv>
              ))}
            </section>
          ))}
          {r.logs?.map((l, i) => (
            <div className="receipt-log" key={i}>
              {l}
            </div>
          ))}
        </ExplorerDialog>
      </div>
    </div>
  );
}
export default function TransactionPage() {
  const { signature = "" } = useParams();
  const q = useQuery({
    queryKey: ["transaction", signature],
    queryFn: () => getTransaction(signature),
    retry: (n, e) =>
      ![400, 404].includes((e as { status?: number }).status ?? 0) && n < 2,
  });
  const r = q.data?.receipt;
  useEffect(() => {
    document.title = composeBrowserTitle(
      r?.kind
        ? [titles[r.kind], r.climb?.name].filter(Boolean).join(" · ")
        : null,
      "Transaction",
      "BoulderScan",
    );
    return () => {
      document.title = "BoulderScan";
    };
  }, [r?.kind, r?.climb?.name]);
  if (
    q.isError &&
    [400, 404].includes((q.error as { status?: number }).status ?? 0)
  )
    return <TransactionNotFound id={signature} />;
  if (q.isError)
    return (
      <ErrorState title="Transaction unavailable" onRetry={() => q.refetch()} />
    );
  return q.data ? (
    <TransactionPageContent data={q.data} />
  ) : (
    <div className="receipt-room" aria-busy="true">
      <div className="receipt-column">
        <h1>Transaction</h1>
      </div>
    </div>
  );
}
