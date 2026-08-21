// Fixture for rules/raw-caught-to-logger.yml — the `files:` constraint.
//
// A GENUINE violation outside both scope globs. No marker: it must not be
// reported. Client-side components legitimately log raw errors to the browser
// console; the policy is about SERVER logs reaching Axiom as "[object Object]".
//
// This file is also why the fixture is a directory tree rather than a single
// file. Scope cannot be tested from one path, and the un-tested `files:` key is
// exactly what made the previous fixture return zero findings while exiting 0.

try { a(); } catch (e2) { console.error('ctx:', e2); }
