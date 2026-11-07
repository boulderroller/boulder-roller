import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { expect, it, vi } from "vitest";
vi.mock("@/components/ground/ObservatoryGround", () => ({
  default: () => null,
}));
import { AccountPageContent } from "./AccountPage";
const wallet = "A".repeat(32);
it("renders the Account room with strict absence and wallet-only identity", () => {
  const html = renderToStaticMarkup(
    <StaticRouter location="/account/test">
      <AccountPageContent
        pubkey={wallet}
        room={{
          ground: [],
          positions: [],
          completions: [],
          settlements: [],
          activity: [],
          balances: [],
        }}
      />
    </StaticRouter>,
  );
  for (const word of [
    "Rides attested",
    "Seats",
    "Crowns",
    "Positions",
    "Balances",
    "Completions",
    "Settlements",
    "Activity",
  ])
    expect(html).toContain(word);
  for (const word of [
    "Protocol Summary",
    "Beetle",
    "Training Load",
    "—",
    ">0<",
    "Since Week",
  ])
    expect(html).not.toContain(word);
  expect(html).toContain(wallet);
});
it("uses public handle and keeps custody rows distinct", () => {
  const html = renderToStaticMarkup(
    <StaticRouter location="/account/test">
      <AccountPageContent
        pubkey={wallet}
        room={{
          handle: "@tim",
          ground: [],
          positions: [],
          completions: [],
          settlements: [],
          activity: [],
          balances: [
            { account: "B".repeat(32), symbol: "CAL", amount: "1000000000" },
            { account: "C".repeat(32), symbol: "CAL", amount: "2000000000" },
          ],
        }}
      />
    </StaticRouter>,
  );
  expect(html).toContain("@tim");
  expect(html.match(/CAL in wallet/g)).toHaveLength(2);
  expect(html).not.toContain("3 CAL");
  expect(html).not.toContain(`/account/${"B".repeat(32)}`);
});
