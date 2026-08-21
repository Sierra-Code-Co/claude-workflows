// Trimmed from mtg-cube-ai web/src/lib/server/decks.ts (#2099).
//
// The gold-set finding on this file is REAL and must survive the replay
// untouched: switching the comparator orphans dedup keys already persisted
// under the old ordering. It rests on judgment about historical rows, not on
// a checkable fact about this checkout, so it carries claim: null.

export function commanderDedupKey(names: string[]): string {
	return [...names].sort(byteStableCompare).join('|');
}

/** Byte-stable. `localeCompare` is locale- and ICU-version-dependent, so it
 *  cannot back a PERSISTED sort key. */
export function byteStableCompare(a: string, b: string): number {
	return a < b ? -1 : a > b ? 1 : 0;
}
