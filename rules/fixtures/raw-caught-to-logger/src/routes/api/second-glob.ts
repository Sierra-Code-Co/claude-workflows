// Fixture for rules/raw-caught-to-logger.yml — the SECOND `files:` glob.
//
// `files:` lists two globs. The recalled fixture exercised one, so a rule that
// silently lost `**/src/routes/api/**/*.ts` would have passed its own proof
// while going blind to every API route in the target repo — which is where the
// original sweep's violations actually lived.

export const ssr = false;

try { a(); } catch (e) { console.error('[api] handler failed:', e); } // sg-expect
