// Fixture for rules/raw-caught-to-logger.yml — the `ignores:` constraint.
//
// A GENUINE violation, byte-identical in shape to P2 in violations.ts, in a
// file the policy excludes. No marker: it must not be reported. The test
// proves the exclusion is doing the work by scanning this same text at an
// in-scope path and asserting it DOES match there — otherwise "no findings
// here" would be satisfied by a rule that finds nothing anywhere.

try { a(); } catch (e2) { console.error('ctx:', e2); }
