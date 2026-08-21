// Added in mtg-cube-ai #2099, in the same diff as the comparator change.
//
// This file is the whole refutation of gold-set finding G2 ("no test coverage
// added"). The reviewer could not see it because added test files were not
// marked as tests in the prompt — FR-010, US5's measure. US2's job is narrower:
// enumerate the checkout and observe that the symbol IS referenced from a test.

import { describe, expect, it } from 'vitest';
import { byteStableCompare, commanderDedupKey } from './deck-dedup';

describe('commanderDedupKey', () => {
	it('is order-independent', () => {
		expect(commanderDedupKey(['b', 'a'])).toBe(commanderDedupKey(['a', 'b']));
	});

	// Pinned to a literal, not to the function's own output. The first version
	// of this test fed the function its own result and passed under the very
	// bug it was written to catch.
	it('orders by byte, not by collation', () => {
		expect(commanderDedupKey(['Ätherling', 'Zurgo'])).toBe('Zurgo|Ätherling');
	});

	it('compares bytes', () => {
		expect(byteStableCompare('Z', 'Ä')).toBe(-1);
	});
});
