// Trimmed from mtg-cube-ai web/src/lib/server/describe-thrown.ts (#2101).
// Bodies elided — the verifier reads declarations.
//
// The gold-set finding claimed `describeThrown(...).errMessage may be
// undefined` on the theory that the function returns `{ name, message }`.
// The declared return type below is what refutes it, and it is reproduced
// exactly: the fields are errName / errMessage / errCode.

export interface ThrownDescription {
	/** Never "object"; falls back to the runtime type name. */
	errName: string;
	/** Never "[object Object]"; capped at 300 chars. */
	errMessage: string;
	/** PostgREST code when the throw came from postgrest-js, else null. */
	errCode: string | null;
}

export function describeThrown(e: unknown): ThrownDescription {
	return { errName: 'Error', errMessage: String(e), errCode: null };
}
