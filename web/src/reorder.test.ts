import { describe, expect, it } from "vitest";
import { dropIndex, keyMove, move, positionLabel, reconcilePending, samePermutation } from "./reorder";

describe("move", () => {
  it("moves an item and returns a copy", () => {
    const list = ["a", "b", "c", "d"];
    expect(move(list, 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(move(list, 3, 0)).toEqual(["d", "a", "b", "c"]);
    expect(list).toEqual(["a", "b", "c", "d"]);
  });

  it("clamps the target and ignores an out-of-range source", () => {
    expect(move(["a", "b", "c"], 0, 99)).toEqual(["b", "c", "a"]);
    expect(move(["a", "b", "c"], 2, -5)).toEqual(["c", "a", "b"]);
    expect(move(["a", "b"], 5, 0)).toEqual(["a", "b"]);
    expect(move(["a", "b"], -1, 0)).toEqual(["a", "b"]);
    expect(move([], 0, 0)).toEqual([]);
  });
});

describe("dropIndex", () => {
  const mids = [10, 30, 50];
  it("counts the other rows above the pointer", () => {
    expect(dropIndex(mids, -100)).toBe(0);
    expect(dropIndex(mids, 10)).toBe(0);
    expect(dropIndex(mids, 11)).toBe(1);
    expect(dropIndex(mids, 49)).toBe(2);
    expect(dropIndex(mids, 1000)).toBe(3);
    expect(dropIndex([], 5)).toBe(0);
  });
});

describe("keyMove", () => {
  const ids = ["a", "b", "c"];
  it("moves by one or to either end", () => {
    expect(keyMove(ids, "b", "ArrowUp")).toEqual(["b", "a", "c"]);
    expect(keyMove(ids, "b", "ArrowDown")).toEqual(["a", "c", "b"]);
    expect(keyMove(ids, "c", "Home")).toEqual(["c", "a", "b"]);
    expect(keyMove(ids, "a", "End")).toEqual(["b", "c", "a"]);
  });

  it("returns null when nothing would move", () => {
    expect(keyMove(ids, "a", "ArrowUp")).toBeNull();
    expect(keyMove(ids, "a", "Home")).toBeNull();
    expect(keyMove(ids, "c", "ArrowDown")).toBeNull();
    expect(keyMove(ids, "c", "End")).toBeNull();
    expect(keyMove(ids, "x", "ArrowDown")).toBeNull();
  });
});

describe("samePermutation", () => {
  it("requires the same distinct ids", () => {
    expect(samePermutation(["a", "b"], ["b", "a"])).toBe(true);
    expect(samePermutation([], [])).toBe(true);
    expect(samePermutation(["a", "b"], ["a"])).toBe(false);
    expect(samePermutation(["a", "a"], ["a", "b"])).toBe(false);
    expect(samePermutation(["a", "b"], ["a", "a"])).toBe(false);
    expect(samePermutation(["a", "b"], ["a", "c"])).toBe(false);
  });
});

describe("positionLabel", () => {
  it("is one-based", () => {
    expect(positionLabel(1, 5)).toBe("第 2 / 5 个");
  });
});

describe("reconcilePending", () => {
  it("keeps a pending order that is still a permutation", () => {
    expect(reconcilePending(null, ["a"])).toBeNull();
    expect(reconcilePending(["b", "a"], ["a", "b"])).toEqual(["b", "a"]);
  });

  it("drops ids removed on the server", () => {
    expect(reconcilePending(["c", "b", "a"], ["a", "c"])).toEqual(["c", "a"]);
  });

  it("abandons the local order when the server gained an account", () => {
    expect(reconcilePending(["b", "a"], ["a", "b", "c"])).toBeNull();
  });
});
