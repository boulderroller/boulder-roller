import { Link } from "react-router-dom";
import { ReactNode } from "react";

type SectionProps = {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
};

type StatCardProps = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
};

export function SectionCard({
  title,
  eyebrow,
  actions,
  children,
}: SectionProps) {
  return (
    <section className="section-card">
      <div className="section-card__header">
        <div>
          {eyebrow ? (
            <div className="section-card__eyebrow">{eyebrow}</div>
          ) : null}
          <h2>{title}</h2>
        </div>
        {actions ? <div>{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function StatCard({ label, value, detail }: StatCardProps) {
  return (
    <article className="stat-card">
      <div className="stat-card__label">{label}</div>
      <div className="stat-card__value">{value}</div>
      {detail ? <div className="stat-card__detail">{detail}</div> : null}
    </article>
  );
}

/** One linked ledger-row primitive shared by the Week and Climb rooms. */
export function LedgerRow({
  to,
  mark,
  name,
  detail,
  value,
  className = "",
  ...props
}: {
  to?: string;
  mark?: ReactNode;
  name: ReactNode;
  detail?: ReactNode;
  value?: ReactNode;
  className?: string;
  "data-event-kind"?: string;
  "data-ledger-row"?: boolean;
}) {
  const content = (
    <>
      <i aria-hidden="true">{mark}</i>
      <div>
        <b>{name}</b>
        {detail ? <span>{detail}</span> : null}
      </div>
      <em>{value}</em>
    </>
  );
  return to ? (
    <Link to={to} className={`observatory-row ${className}`} {...props}>
      {content}
    </Link>
  ) : (
    <div className={`observatory-row ${className}`} {...props}>
      {content}
    </div>
  );
}

export function LedgerKv({
  label,
  children,
  to,
  ...props
}: {
  label: string;
  children: ReactNode;
  to?: string;
  "data-registration-key"?: string;
  "data-ledger-row"?: boolean;
}) {
  const content = (
    <>
      <span>{label}</span>
      <b>
        {children}
        {to ? (
          <span className="ledger-chevron" aria-hidden="true">
            {" "}
            ›
          </span>
        ) : null}
      </b>
    </>
  );
  return to ? (
    <Link className="week-kv ledger-kv" to={to} {...props}>
      {content}
    </Link>
  ) : (
    <div className="week-kv ledger-kv" {...props}>
      {content}
    </div>
  );
}
