// Pure reorder helpers for the accounts panel. The server's config order is the
// only source of truth; these compute a local, optimistic permutation that is
// committed as a whole with PUT /api/v1/accounts/order.

/** A copy of `list` with the item at `from` moved to `to` (clamped). Out-of-range `from` is a no-op copy. */
export function move<T>(list: readonly T[], from: number, to: number): T[] {
  const copy = list.slice();
  if (!Number.isInteger(from) || from < 0 || from >= copy.length) return copy;
  const target = Math.max(0, Math.min(copy.length - 1, Math.trunc(to)));
  const [item] = copy.splice(from, 1) as [T];
  copy.splice(target, 0, item);
  return copy;
}

/**
 * The index a dragged row lands on. `midpoints` are the vertical midpoints of
 * the *other* rows, top to bottom, in the same coordinate space as `y`; the
 * result is how many of them lie above `y` (0..midpoints.length).
 */
export function dropIndex(midpoints: readonly number[], y: number): number {
  let index = 0;
  for (const mid of midpoints) {
    if (y > mid) index += 1;
    else break;
  }
  return index;
}

export type MoveKey = "ArrowUp" | "ArrowDown" | "Home" | "End";

export function isMoveKey(key: string): key is MoveKey {
  return key === "ArrowUp" || key === "ArrowDown" || key === "Home" || key === "End";
}

/** The order after a keyboard move, or null when the key would not move `id`. */
export function keyMove(ids: readonly string[], id: string, key: MoveKey): string[] | null {
  const from = ids.indexOf(id);
  if (from < 0) return null;
  const last = ids.length - 1;
  const to = key === "ArrowUp" ? from - 1 : key === "ArrowDown" ? from + 1 : key === "Home" ? 0 : last;
  if (to < 0 || to > last || to === from) return null;
  return move(ids, from, to);
}

/** Whether `a` and `b` hold exactly the same distinct ids (in any order). */
export function samePermutation(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  if (set.size !== a.length) return false;
  return b.every((id) => set.has(id)) && new Set(b).size === b.length;
}

export function sameOrder(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

/** "第 2 / 5 个" for a zero-based index. */
export function positionLabel(index: number, total: number): string {
  return `第 ${index + 1} / ${total} 个`;
}

/**
 * Reconcile a not-yet-committed local order with a fresh server list: ids the
 * server no longer has are dropped. If the rest is not a permutation of the
 * server ids (an account was added elsewhere), the local order is abandoned (null).
 */
export function reconcilePending(pending: readonly string[] | null, serverIds: readonly string[]): string[] | null {
  if (pending === null) return null;
  const present = new Set(serverIds);
  const kept = pending.filter((id) => present.has(id));
  return samePermutation(kept, serverIds) ? kept : null;
}
