// Trimmed from mtg-cube-ai web/src/lib/server/describe-thrown.guard.ts (#2101).
//
// Two gold-set findings land here.
//
// G5 (REAL AND STILL LIVE): `offenders()` pre-strips block comments with a
// regex before parsing. On the proving ground's +server.ts:3511 the `/*` inside
// a LINE comment reading `// delegate to /api/workflow/tools/* ...` opens a fake
// block comment that the regex closes 765 lines later at the `*/` inside a regex
// literal, deleting a 33,904-character span containing 6 live console calls.
// Constitution Principle III / FR-006. It must survive the replay.
//
// G3 (FALSE): the reviewer claimed `isCallExpression` misses optional-chain
// calls, so `a?.b()` slips past the guard. Settling that means asking the
// TypeScript compiler how it parses `a?.b()` — an `execute` claim, deferred by
// FR-024. The replay must resolve it to `unverifiable`, NOT to `confirmed`.

import ts from 'typescript';

export function stripBlockComments(src: string): string {
	return src.replace(/\/\*[\s\S]*?\*\//g, '');
}

export function offenders(src: string): ts.Node[] {
	const stripped = stripBlockComments(src);
	const sf = ts.createSourceFile('x.ts', stripped, ts.ScriptTarget.Latest, true);
	const out: ts.Node[] = [];
	const walk = (n: ts.Node) => {
		if (ts.isCallExpression(n)) out.push(n);
		ts.forEachChild(n, walk);
	};
	walk(sf);
	return out;
}
