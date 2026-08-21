// Fixture for rules/raw-caught-to-logger.yml — in-scope file.
//
// A line carrying the marker `sg-expect` MUST be reported by the rule. Every
// other line MUST NOT be. tests/unit/test_structural_rules.py asserts SET
// EQUALITY between the two, so an over-match fails as loudly as a miss — a
// rule that flags everything is not a passing rule.
//
// The shapes below are DERIVED from the rule's own constraints (FR-008a), not
// recalled. The rule has five constraints plus two scope constraints, so each
// gets a near-miss negative that violates exactly that one and satisfies the
// rest. Recall produced neither the `console.log` positive nor the two callee
// near-misses; the alternation had three members and the recalled list covered
// two of them.

// --- POSITIVES ---------------------------------------------------------------

// P1: single argument.
try { a(); } catch (e1) { console.error(e1); } // sg-expect

// P2: trailing argument, no trailing comma.
try { a(); } catch (e2) { console.error('ctx:', e2); } // sg-expect

// P3: multi-line, argument on its own line, TRAILING COMMA. This is the
// dominant formatting in the target codebase and the shape that every regex
// written for this sweep was blind to — seven live sites.
try { a(); } catch (e3) {
  console.error(
    '[spec207] paste fast path failed:',
    e3, // sg-expect
  );
}

// P4: non-final argument.
try { a(); } catch (e4) { console.error('ctx:', e4, 'more'); } // sg-expect

// P5: template-literal sibling argument.
try { a(); } catch (e5) { console.error(`ctx ${1}`, e5); } // sg-expect

// P6: console.warn — second member of the alternation.
try { a(); } catch (e6) { console.warn('ctx:', e6); } // sg-expect

// P7: console.log — THIRD member of the alternation, and the one the recalled
// shape list omitted. A rule whose regex read `^console\.(error|warn)$` passes
// every other case in this file.
try { a(); } catch (e7) { console.log('ctx:', e7); } // sg-expect

// P8: a real violation immediately after a LINE comment containing `/*`. The
// killer for comment-stripping regexes, which treat the rest of the file as
// commented out from here on.
// delegate to /api/workflow/tools/* which enforces ownership
try { a(); } catch (e8) { console.error('after the fake comment opener:', e8); } // sg-expect
const re = /\s*\n+\s*/g;
void re;

// P9: optional call. The rule matches this, and nothing pinned it — so the
// behaviour was undocumented rather than decided, and a grammar change could
// have silently dropped it. Surfaced by the mutation probe while building
// tests/proofs/derive_shapes.py, not by recall.
try { a(); } catch (e9) { console.error?.('ctx:', e9); } // sg-expect

// --- NEAR-MISS NEGATIVES: one violated constraint each ------------------------

// N1 (violates: identifier is a direct argument). The caught value is wrapped,
// which is the remediation itself.
try { a(); } catch (n1) { console.error('ctx:', describeThrown(n1).errMessage); }

// N2 (violates: callee is console.*). Same shape, different logger. A rule
// relaxed to `\.(error|warn|log)$` — a natural way to "support more loggers" —
// starts matching here while every positive above still passes.
try { a(); } catch (n2) { logger.error('ctx:', n2); }

// N3 (violates: method is one of error|warn|log). A rule relaxed to
// `^console\.` matches here while every positive above still passes.
try { a(); } catch (n3) { console.debug('ctx:', n3); }

// N4 (violates: is inside a console call's arguments). The binding is
// referenced, but not passed to a logger at all.
try { a(); } catch (n4) { const m = n4; void m; }

// N5 (violates: is inside a catch clause). Same call shape, ordinary variable.
const plain = 5; console.error('ctx:', plain);

// N6 (violates: IS the catch binding). An identifier inside a catch block that
// is not the caught value. This is what metavariable unification buys: without
// it the rule also flags `modelId`, `idx`, and `toolCallId`.
try { a(); } catch (n6) { console.error('ctx:', modelId, describeThrown(n6).errMessage); }

// N9 (violates: the enclosing binder is a catch_clause). An arrow function's
// single unparenthesized parameter also sits in a `parameter` field, so with
// `kind: catch_clause` relaxed the rule flags these too.
//
// THE VALIDATOR FOUND THIS, NOT THE AUTHOR. Eleven shapes were written from
// recall and none of them distinguished "the caught value" from "any single-arg
// arrow parameter"; dropping `kind: catch_clause` changed nothing the fixture
// could observe. That is precisely the hole FR-008a describes.
//
// It is also the boundary that matters most in real code: `.catch(e => ...)` is
// the dominant promise idiom, and this rule deliberately does NOT flag it —
// tightening it to do so is a policy change that must break these two lines
// first. Note the parenthesized form `(e) => ...` uses `formal_parameters`, not
// `parameter`, and so cannot serve as this negative.
const arrowLogger = n9 => console.error('ctx:', n9);
void arrowLogger;
work().catch(n9b => console.error('failed:', n9b));

// N10: the PARENTHESIZED arrow form. Not a near-miss for any constraint — it
// uses `formal_parameters`, so relaxing `kind: catch_clause` does not reach it —
// but pinned anyway, because it is the same source-level shape as N9 and its
// behaviour is currently accidental rather than decided. If the rule is ever
// widened to formal_parameters (a reasonable policy change, since
// `.catch((e) => console.error(e))` leaks the same way), this line must move
// into the positives deliberately instead of changing verdict unnoticed.
work().catch((n10) => console.error('failed:', n10));

// N7: commented-out decoy.
// console.error('x:', n7);

// N8: block-comment decoy.
/* console.error('x:', n8); */

// --- SHADOWING: the caught value vs. a parameter that merely shares its name --

// P10: an inner arrow that does NOT shadow. The caught value still reaches the
// logger, so this must REPORT — and it is the near-miss for the shadow
// exclusion's own constraints. Drop `field: parameters` or the `$ERR` pattern
// from that clause and the exclusion widens to "any function with parameters",
// suppressing this line. A negation needs near-misses in the opposite
// direction: an over-broad exclusion is invisible except through a positive it
// wrongly swallows.
try { a(); } catch (e10) { void ((_other: unknown) => console.error('ctx:', e10)); } // sg-expect

// P11: same, unparenthesized parameter — the `parameter`-field branch.
try { a(); } catch (e11) { void (_other2 => console.error('ctx:', e11)); } // sg-expect

// N11 (violates: the enclosing binder is a catch_clause). An arrow parameter
// logged from inside a catch clause that binds something ELSE. Relax
// `kind: catch_clause` and the rule walks past the catch to the arrow and
// flags `n11`, which is not a caught value at all.
//
// This shape had to be built because the shadow exclusion below RETIRED the old
// near-miss for that constraint: N9's top-level arrow is now excluded whether or
// not `kind: catch_clause` is present, so dropping it stopped changing anything
// the fixture could observe. Adding a constraint silently un-covered a different
// one — the derivation harness reported it, and it is the reason that harness
// enumerates from the rule instead of trusting a written list.
const n11Outer = n11 => { try { a(); } catch (_x11) { void _x11; console.error('ctx:', n11); } };
void n11Outer;

// N12: arrow parameter SHADOWS the caught value. `e12` inside the arrow is the
// arrow's own binding; the caught value never reaches the logger. Reported by
// CodeRabbit against the propagation PR, in a repo where this gate is BLOCKING
// and a false positive therefore blocks a push.
try { a(); } catch (_e12) { void _e12; void ((_e12: unknown) => console.error('inner:', _e12)); }

// N13: function-expression parameter shadows.
try { a(); } catch (_e13) { void _e13; void (function (_e13: unknown) { console.error('inner:', _e13); }); }

// N14: method parameter shadows.
try { a(); } catch (_e14) { void _e14; void { m(_e14: unknown) { console.error('inner:', _e14); } }; }

// N15: unparenthesized arrow parameter shadows.
try { a(); } catch (_e15) { void _e15; void (_e15 => console.error('inner:', _e15)); }

// P12: a DEFAULT-PARAMETER expression that merely mentions the caught value.
// The arrow binds `value`; `e16` is the caught value being read, so this is a
// real violation. The first version of the shadow exclusion searched the whole
// parameter subtree and swallowed it — a false negative created by the fix for
// a false positive, which is the worse direction and is why the exclusion now
// matches the parameter's binding rather than its text.
try { a(); } catch (e16) { void ((_value = e16) => console.error('ctx:', e16)); } // sg-expect

// P13: DESTRUCTURED parameter binding a different name — still a violation.
try { a(); } catch (e17) { void (({ _other3 }) => console.error('ctx:', e17)); } // sg-expect

// N16: destructured parameter that DOES shadow. Derived from the rule's shape
// rather than reported: if the exclusion keys on the parameter's `pattern`
// field, destructuring has to be handled, and nothing else in this file asks.
try { a(); } catch (e18) { void e18; void (({ e18 }) => console.error('inner:', e18)); }

// P14: a nested function in the BODY binds the caught value's name, but the
// enclosing arrow's own parameter does not. `e19` at the logger is still the
// catch binding, so this reports — and it is the near-miss for `field:
// parameters`. Drop that field and the search finds the inner function's
// parameter anywhere below the enclosing arrow, wrongly suppressing this.
//
// The inner parameter is USED rather than underscore-prefixed: the shape needs
// a parameter literally named `e19`, so satisfying no-unused-vars by renaming
// it would silently retire the near-miss.
try { a(); } catch (e19) {
  void ((_outer) => {
    void ((e19: unknown) => String(e19));
    console.error('ctx:', e19); // sg-expect
  });
}

// --- REST parameters ----------------------------------------------------------
//
// Review reported these as a false positive and proposed adding `rest_pattern`
// to the parameter-kind list. MEASURED AGAINST THE RULE INSTEAD: `...err` parses
// as a `required_parameter` whose `pattern` field IS a `rest_pattern`, so the
// binding branch already reaches it and all four lines below already behaved.
// The finding was posted minutes after that branch landed.
//
// So the RULE needed nothing — but the fixture said nothing about rest
// parameters either way, which is the half of the finding that was real. Silent
// is not the same as correct, and a behaviour no fixture pins is a behaviour
// that can change without anyone noticing.

// N17-N19: a rest parameter that SHADOWS the caught value.
try { a(); } catch (e20) { void e20; void ((...e20) => console.error('inner:', e20)); }
try { a(); } catch (e21) { void e21; void (function (...e21) { console.error('inner:', e21); }); }
try { a(); } catch (e22) { void e22; void ({ m(...e22) { console.error('inner:', e22); } }); }

// P15: a rest parameter with a DIFFERENT name — the caught value still reaches
// the logger, so this reports.
try { a(); } catch (e23) { void ((..._rest) => console.error('ctx:', e23)); } // sg-expect
