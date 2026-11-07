import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { expect, it } from "vitest";
import { TransactionPageContent, TransactionNotFound } from "./TransactionPage";
it("receipt uses ratified sections and words without undecoded figures", () => {
  const html = renderToStaticMarkup(
    <StaticRouter location="/tx/test">
      <TransactionPageContent
        data={{
          signature: "A".repeat(88),
          instructions: [],
          events: [],
          status: "failed",
          slot: null,
          block_time: null,
          fee_lamports: "",
          compute_units: null,
          receipt: { fields: {}, accounts: [] },
        }}
      />
    </StaticRouter>,
  );
  for (const text of ["On chain", "Accounts", "Solana Explorer", "Failed"])
    expect(html).toContain(text);
  for (const text of [
    "Token Flow",
    "Overview",
    "Chain Details",
    "—",
    ">0<",
    "pill",
    ">Fee<",
  ])
    expect(html).not.toContain(text);
});
it("not-found is a single Search door", () => {
  const html = renderToStaticMarkup(
    <StaticRouter location="/tx/missing">
      <TransactionNotFound id="missing" />
    </StaticRouter>,
  );
  expect(html).toContain("Not found");
  expect(html).toContain("Search");
  expect(html).not.toContain("On chain");
});
import {
  transactionFixture,
  fixtureSignatures,
  receiptKinds,
} from "@/fixtures/transaction-room";
for (const [i, kind] of receiptKinds.entries())
  it(`renders ${kind} as a receipt with account and transaction doors`, () => {
    const data = transactionFixture(fixtureSignatures[i])!;
    const html = renderToStaticMarkup(
      <StaticRouter location="/tx/test">
        <TransactionPageContent data={data} />
      </StaticRouter>,
    );
    expect(html).toContain("/climb/" + data.receipt!.climb!.id);
    expect(html).toContain("/account/" + data.receipt!.rider!.wallet);
    expect(html).toContain("On chain");
    expect(html).toContain("Instructions · 1");
    expect(html).toContain("Solana Explorer");
    const empty = { ...data, receipt: { kind, fields: {}, accounts: [] } };
    const sparse = renderToStaticMarkup(
      <StaticRouter location="/tx/test">
        <TransactionPageContent data={empty} />
      </StaticRouter>,
    );
    for (const missing of [
      "New best",
      "Rank after",
      "Completions counted",
      "Positions paid",
      ">CAL<",
      "DUNG distributed",
      ">Canon<",
    ])
      expect(sparse).not.toContain(missing);
  });
