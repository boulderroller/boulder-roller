import { expect, it } from "vitest";
import { coordinateAtFraction } from "./geometry";
it("scrubs by travelled distance rather than uneven vertex index", () => {
  expect(
    coordinateAtFraction(
      [
        [0, 0],
        [0, 0.001],
        [0, 0.01],
      ],
      0.5,
    )?.[1],
  ).toBeCloseTo(0.005, 6);
  expect(
    coordinateAtFraction(
      [
        [0, 0],
        [0, 0.01],
      ],
      1,
    ),
  ).toEqual([0, 0.01]);
  expect(coordinateAtFraction([], 0)).toBeNull();
  expect(
    coordinateAtFraction(
      [
        [0, NaN],
        [0, 0.01],
      ],
      0.5,
    ),
  ).toBeNull();
});
