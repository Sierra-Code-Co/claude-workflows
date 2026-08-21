// Added in mtg-cube-ai #2101, in the same diff as the guard change.
//
// Refutes gold-set finding G4 ("missing tests for optional-chain forms"). The
// optional-chain shape IS covered here; the reviewer asserted its absence
// without being able to see added test files.

import { describe, expect, it } from 'vitest';
import { offenders, stripBlockComments } from './console-guard';

describe('offenders', () => {
	it('sees a plain call', () => {
		expect(offenders('console.error(e);')).toHaveLength(1);
	});

	it('sees an optional-chain call', () => {
		expect(offenders('logger?.error(e);')).toHaveLength(1);
	});

	it('sees a multi-line call with the argument on its own line', () => {
		expect(offenders('console.error(\n\te,\n);')).toHaveLength(1);
	});
});

describe('stripBlockComments', () => {
	it('removes a real block comment', () => {
		expect(stripBlockComments('a;/* c */b;')).toBe('a;b;');
	});
});
