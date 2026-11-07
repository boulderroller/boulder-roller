import { useEffect, useState } from "react";
import RelativeTime from "@/components/RelativeTime";
import { formatCount, formatStatus } from "@/lib/format";
import type { ScanFreshness } from "@/types";

type FreshnessStampProps = {
  freshness?: ScanFreshness | null;
};

function slotLabel(value: ScanFreshness["max_observed_slot"]): string {
  if (value === null || value === undefined || value === "")
    return "slot pending";
  return `slot ${formatCount(value)}`;
}

function freshnessCopy(freshness: ScanFreshness | null | undefined): string {
  if (!freshness) return "Read model freshness unavailable";
  const readModel = freshness.read_model
    ? formatStatus(freshness.read_model)
    : "Read model";
  const status = freshness.status ? formatStatus(freshness.status) : "Unknown";
  return `${readModel} ${status}`;
}

export default function FreshnessStamp({ freshness }: FreshnessStampProps) {
  const status = freshness?.status ?? "unknown";
  const timestamp =
    freshness?.last_tx_sync_at ??
    freshness?.last_account_sync_at ??
    freshness?.loaded_at ??
    null;

  return (
    <div className={`freshness-stamp freshness-stamp--${status}`}>
      <span className="freshness-stamp__status">
        {freshnessCopy(freshness)}
      </span>
      <span className="freshness-stamp__detail">
        {slotLabel(freshness?.max_observed_slot)}
        {timestamp ? (
          <>
            {" "}
            · <RelativeTime value={timestamp} />
          </>
        ) : null}
      </span>
    </div>
  );
}

/** Conservative indexer checkpoint; an absent checkpoint has no replacement copy. */
export function IndexedStamp({
  indexed,
}: {
  indexed?: { slot: number; at: string; age_seconds: number };
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);
  if (!indexed) return null;
  const age = Math.max(
    indexed.age_seconds,
    Math.floor((now - Date.parse(indexed.at)) / 1000),
  );
  const text =
    age < 60
      ? `${age}s`
      : age < 3600
        ? `${Math.floor(age / 60)}m`
        : age < 86400
          ? `${Math.floor(age / 3600)}h`
          : `${Math.floor(age / 86400)}d`;
  return (
    <div className="week-stamp">
      Indexed to slot {formatCount(indexed.slot)} · {text} ago
    </div>
  );
}
