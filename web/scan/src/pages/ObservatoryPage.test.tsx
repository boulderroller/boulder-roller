import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
vi.mock("@/components/ground/ObservatoryGround", () => ({
  default: () => null,
}));
import { weekRows, RecentRow } from "./ObservatoryPage";
import { fixtureObservatory } from "@/fixtures/data";
describe("Week page truth", () => {
  it("leaves every unindexed figure absent, without zero or substitute sentences", () => {
    expect(weekRows({})).toEqual([]);
    expect(
      weekRows({
        climbs_registered: 0,
        cal_deposited: "0",
        riders: 0,
        rides_attested: 0,
        dung_distributed: "0",
      }),
    ).toEqual([]);
    expect(weekRows(fixtureObservatory.week!)).toHaveLength(5);
  });
  it("links each attested Recent object to its transaction and omits unknown events", () => {
    const event = fixtureObservatory.recent_events[0];
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <RecentRow event={event} />
      </MemoryRouter>,
    );
    expect(html).toContain(`/tx/${event.signature}`);
    expect(html).toContain("Manayunk Wall");
    expect(html).toContain("+5.05 DUNG");
    expect(
      renderToStaticMarkup(
        <MemoryRouter>
          <RecentRow event={{ ...event, object: undefined }} />
        </MemoryRouter>,
      ),
    ).toBe("");
  });
});
