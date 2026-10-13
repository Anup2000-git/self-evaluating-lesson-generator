import { describe, expect, it } from "vitest";
import { niceMax, niceTicks } from "./ChartFrame";

describe("chart scales", () => {
  it("uses whole-number steps for counts", () => {
    expect(niceTicks(4, { integer: true })).toEqual([0, 1, 2, 3, 4]);
    expect(niceTicks(7, { integer: true })).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(0, { integer: true })).toEqual([0, 1]);
  });

  it("uses clean fractional steps for rates", () => {
    expect(niceTicks(0.75)).toEqual([0, 0.2, 0.4, 0.6, 0.8]);
  });

  it("rounds a maximum up to a clean value", () => {
    expect(niceMax(0.75)).toBe(1);
    expect(niceMax(37)).toBe(50);
  });
});
