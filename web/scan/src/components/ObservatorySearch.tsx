import ExplorerDialog from './ExplorerDialog';
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { classifySearchInput, searchTarget } from "@/lib/search";
import { resolveUsernameAccount } from "@/lib/api";
import type { GroundClimb } from "@/types";
import "@/styles/portal-search-sheet.css";

export default function ObservatorySearch({
  climbs, triggerLabel,
}: {
  climbs: GroundClimb[]; triggerLabel?:string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<string | null>(null);
  const [rider, setRider] = useState<{
    username: string;
    pubkey: string;
  } | null>(null);
  const close = () => {
    dialog.current?.close();
    trigger.current?.focus();
  };
  useEffect(() => {
    let cancelled = false;
    setRider(null);
    const match = classifySearchInput(query);
    if (match?.type !== "username") return;
    const timer = setTimeout(() => {
      void resolveUsernameAccount(match.value)
        .then((result) => {
          if (!cancelled) setRider(result);
        })
        .catch(() => {});
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);
  const q = query.trim().toLowerCase();
  const climbResults = climbs.filter(
    (c) =>
      c.name.toLowerCase().includes(q) ||
      c.id === q ||
      query.endsWith(`/climb/${c.id}`),
  );
  const target = searchTarget(query),
    match = classifySearchInput(query);
  const groups = [
    {
      name: "Climbs",
      glyph: "△",
      results: climbResults.map((c) => ({
        name: c.name,
        to: `/climb/${c.id}`,
      })),
    },
    {
      name: "Riders",
      glyph: "○",
      results: rider
        ? [{ name: `@${rider.username}`, to: `/account/${rider.pubkey}` }]
        : match?.type === "account" && target
          ? [{ name: match.value, to: target }]
          : [],
    },
    {
      name: "Transactions",
      glyph: "□",
      results:
        match?.type === "transaction" && target
          ? [{ name: match.value, to: target }]
          : [],
    },
  ];
  return (
    <>
      <button
        ref={trigger}
        className="observatory-search"
        onClick={() => {dialog.current?.showModal(); field.current?.focus();}}
      >
        <i aria-hidden="true" />
        {triggerLabel ?? "Search climbs, riders, transactions"}
      </button>
      <ExplorerDialog
        ref={dialog}
        className="observatory-search-sheet search-sheet"
        aria-label="Search"
        onClick={(e) => {
          if (e.target === dialog.current) close();
        }}
        onCancel={() => trigger.current?.focus()}
      >
        <div className="observatory-search-bar">
          <b>Search</b>
          <button onClick={close}>Done</button>
        </div>
        <div className="search-sheet__field">
          <input
            ref={field}
            className="search-modal-input"
            aria-label="Search climbs, riders, transactions"
            placeholder="Search climbs, riders, transactions"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="search-sheet__words">
          {groups.map((g) => (
            <button
              key={g.name}
              className={`search-modal-category ${scope === g.name ? "search-modal-category--active" : ""}`}
              aria-pressed={scope === g.name}
              onClick={() => setScope(scope === g.name ? null : g.name)}
            >
              {g.name}
            </button>
          ))}
        </div>
        <div className="search-sheet__list">
          {groups
            .filter((g) => !scope || scope === g.name)
            .map((g) =>
              g.results.length > 0 ? (
                <section key={g.name}>
                  <div className="search-sheet__group-head">{g.name}</div>
                  {g.results.map((r) => (
                    <Link
                      key={r.to}
                      to={r.to}
                      className="search-modal-result"
                      onClick={close}
                    >
                      <span aria-hidden="true">{g.glyph}</span>
                      <span className="search-modal-result__title">
                        {r.name}
                      </span>
                      <span aria-hidden="true">›</span>
                    </Link>
                  ))}
                </section>
              ) : null,
            )}
        </div>
      </ExplorerDialog>
    </>
  );
}
