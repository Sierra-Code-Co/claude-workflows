# Vendor-gate defect log — `preflight-vendor-review`

**This is the single copy.** Until 2026-09-02 this history lived in `dotfiles/claude/CLAUDE.md`,
inside the pre-push gate section, because that is where the guard itself lived when it was nine
lines of shell in a Markdown block and there was nowhere else to put the account of its rounds.
The guard moved into `scripts/preflight-vendor-review.sh` on 2026-08-31 and the history did not
follow it. It stayed in a file that loads into the context of **every** Claude Code session on
this machine, in every repository, including ones with no vendor gate in them — twelve rounds of
narrative, read in full every time to decide nothing. **10,180 bytes**, which is a frozen
historical measurement rather than a live figure: it is what the nine moved paragraphs weighed in
`dotfiles/claude/CLAUDE.md` at `git show HEAD:dotfiles/claude/CLAUDE.md` on the day of the move,
and it cannot go stale because the lines it counts no longer exist there. Its sibling's log
was collapsed to one copy the day before for the staleness surface; this one is being moved for
the same reason plus that one. `dotfiles/claude/CLAUDE.md` now carries the operational rules the
rounds produced and the lessons that generalise out of them, and points here for the incidents.

**This is a SEPARATE FILE from `scripts/vendor-gate-defect-log.md` rather than a part appended
to it, and the reason is that file's own subject.** It opens by counting its defects and
classifying them — how many were the same defect, how many had a test that could not see, which
single entry breaks each claim — and every one of those figures is scoped to
`bounded-vendor-review`. Adding a second guard's rounds under the same numbered-defect vocabulary
makes each of those counts ambiguous without changing a character of them, which is the exact
failure that log records two whole review rounds being spent on. Two files with unambiguous
scopes beat one file with a contested denominator.

**Read the text below as if you were reading `dotfiles/claude/CLAUDE.md`.** It was moved verbatim
rather than rewritten, so "this Markdown block", "this file", "this section", and "above" refer to
that document and its pre-push gate section, not to this one. Rewriting measured history to fix
the pronouns is how a fresh false claim gets introduced into a record whose whole subject is
false claims — the sibling log states this rule about itself, and it applies here for the same
reason. One consequence to read past: the first paragraph's "twelve consecutive review rounds is
why it no longer is" was written when the guard had just moved into a script, and "at the end"
in its second sentence means at the end of the enumeration below.

**EVERY PATH BELOW IS RELATIVE TO `internal-claude-workflows`, AND THIS FILE IS BYTE-IDENTICAL IN
`internal-speckit-template`.** Same arrangement as the sibling log, and `cmp -s` across the two
repos is the only thing keeping the two accounts from forking — nothing in CI enforces it as of
2026-09-02, for either file. In the template the skills call `scripts/preflight-vendor-review.sh`
by repo-relative path rather than the installed `~/.local/bin` name, because a bootstrapped repo
has to work before anything is installed; `dotfiles/` exists only in this repo, so a reference
to it below is a dead path in the copy you are reading rather than a broken link.

**The sibling guard's own history is not here.** `bounded-vendor-review` has its own account, in
`scripts/vendor-gate-defect-log.md`, and the two guards share one lesson and no code.

## The rounds

Twelve of them, on one lesson: **a check whose failure is indistinguishable from its success is
not a check.** No count of how many were fail-open is written here, because the enumeration
below is the only place that number can be read without going stale — the sibling log lost two
review rounds to exactly that arithmetic. Rounds 1 through 7 are one paragraph, as they were
written; 8 through 12 have one each. Read the enumeration, not a summary of it, and add to it
rather than restating it anywhere.

### Rounds 1 through 7 — the same defect, seven times

**This guard was nine lines of shell inside this Markdown block until 2026-08-31, and twelve consecutive review rounds is why it no longer is.** Seven of them were the same defect; the eighth through twelfth are at the end. In order: it was a bare pipeline rather than an `if`, so its clean result (`grep` exiting 1) aborted the gate under `set -e`; then `if git status --porcelain -uall | grep '^??'` reported the *pipeline's* status, so a failing `git status` left grep reading empty input, exiting 1, and the proceed branch running — the guard said "clean worktree" precisely when it could not see the worktree; then the guard sat beside its own explanation rather than inside the command anyone would copy; then that was "fixed" by marking the copyable blocks with a comment saying the guard still applies, and a comment is not a guard; then `printf '%s\n' "$w" | grep -q '^??'` fell open under `pipefail`, because `grep -q` exits at the first match, `printf` takes `SIGPIPE` and exits 141, and 141 became the pipeline's status — the guard ruled the tree clean *because* it found too many untracked files to finish listing them (measured 2026-08-29: correct at 3 files, open at 20,000; the trigger is the 64 KiB pipe buffer, so there is no safe file count); then it ran once rather than twice; and finally `if untracked=$(grep '^??' <<<"$worktree")` collapsed grep's three outcomes into two, so a `grep` that could not run read as a clean tree (measured 2026-08-31 with a stub exiting 2: the clean-tree pass at exit 0).

Every one of those seven fixes was correct and every one left the next hole, and all seven are the same defect wearing different clothes: **a check whose failure is indistinguishable from its success is not a check.** The lesson stopped being about any individual fix. A shell guard living in a Markdown paragraph has no mechanism to be wrong out loud, so the seventh round did what the sixth round's own closing sentence said to do — moved it into `scripts/preflight-vendor-review.sh` with `scripts/test-preflight-vendor-review.sh` behind it, which hands it a dirty worktree, an edited tracked file, a non-repository, a broken helper, each of git's four location variables one at a time, and 20,000 untracked files, and fails if any of them passes. Three of its cases carry anti-vacuity assertions that reconstruct a retired form and fail if it *stops* behaving as it did, because a green test that can no longer distinguish the fix from the bug reads as proof and is not.

### Round 8 — it read only untracked files

**An eighth round widened it, and that one was not a fail-open.** It checked `^??` alone until 2026-08-31, on the reasoning that `--include-untracked` is what routes an unscanned file to the vendor while a tracked file's edits are already reachable by gitleaks. The second half was false in this file's own measured numbers: leg 1 diffs `$BASE...HEAD`, so an unstaged or staged edit is read by no scan in the gate, and the guard passed a staged credential in a tracked file without comment. Widening costs nothing in the intended workflow, where the commit prerequisite means the tree is clean by definition — a dirty tree at gate time means the prerequisite was skipped or the tree moved mid-gate, and both are reasons to stop. The same round removed the last `grep` from the decision: it is now `[ -n "$worktree" ]` on a variable already in hand, with `awk` running only *below* the refusal to word it. Rounds 2, 5 and 7 were each one helper whose operational error was indistinguishable from "found nothing", sitting above the decision; a test with no command in it cannot have that bug, and a broken helper below the decision can garble a refusal but never manufacture a pass.

### Round 9 — the environment aimed it at another repository

**A ninth round, and it was a fail-open again — this time from the environment rather than the shell.** With `GIT_DIR`/`GIT_WORK_TREE` exported, `git status` inside the script inspected *that* repository no matter which directory the script had entered, and the success line still named the directory it was pointed at, because `pwd` was honest while `git` read somewhere else. Reproduced 2026-08-31 with two scratch repos: aimed at a dirty tree holding an unscanned untracked file, with the variables pointing at a clean one, it printed `clean worktree in .../dirty` and exited **0**. A confident answer about the wrong subject is worse than an error, and it is not exotic — git exports these to every hook it runs, so wiring the gate into a pre-push hook would have armed it. `GIT_INDEX_FILE` is the same class one step in, since it redefines what "staged" means. That round unset all four.

### Round 10 — unsetting fixed one process, so it refuses instead

**A tenth round, and it is why the script now REFUSES rather than unsetting.** Unsetting fixes one process and nothing else: the gate is an `&&` chain, so `review-plan-v2` and `coderabbit review` run in *your* shell with *your* environment and inherit `GIT_DIR` and friends regardless — the vendor leg can enumerate a repository the guard never inspected, which is the original defect with an extra step in it. A child cannot unset a variable in its parent, so the only honest move is to stop the chain: the script exits **2** while any of `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR` is set, names the offenders, and tells you to unset them in your shell or run the whole gate under `env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR`. To aim it at a repository, pass `REPO_ROOT`. The same round closed two test defects: `GIT_COMMON_DIR` had no case at all while the docs implied all four were covered, and the `GIT_INDEX_FILE` case was **vacuous** — it used an empty index file, and an empty index is a broken file rather than a redefinition of "staged" (measured 2026-08-31: `GIT_INDEX_FILE=/tmp/empty git status --porcelain` exits **128**, `index file smaller than expected`), so it passed through the fail-closed path for unreadable repositories and proved nothing. There is now one case per variable set alone on a clean tree, one with a *valid* alternate index built by `git read-tree HEAD`, and one that runs the same clean tree with nothing exported and must pass — without that last one a script refusing everything would score green on all the others. The suite reached 24 cases at that round; neutering the refusal is red on exactly the seven environment cases and nothing else.

### Round 11 — the refusal's own advice could defeat the refusal

**An eleventh round fixed the refusal's own advice, which could defeat the refusal.** `env -u ...` applies to the command it prefixes and nothing else, so a caller told only to "use `env -u`" writes it on `preflight-vendor-review` and leaves the vendor leg inheriting the variables — the guard beaten by following its own instructions. Measured 2026-08-31 with `GIT_DIR` exported: the prefix on the first command of an `&&` chain gave `leg1 sees: unset` and then `leg2 sees: /tmp/other-probe-repo/.git`, while `env -u ... bash -c '<chain>'` gave `unset` for both. The refusal now leads with `unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR` in the caller's own shell, shows the wrapping form second, and says outright that a prefix on one leg covers only that leg. A 25th test case asserts that wording, because advice which defeats the guard is part of the guard. Seen red on that one case by replacing the wrapping form with a bare `env -u` mention.

### Round 12 — set-but-empty read as unset, and nine assertions that could not fail

**A twelfth round, and the code defect is one character while the test defect is nine assertions that could not fail.** The refusal tested `[ -n "${!v:-}" ]`, which cannot see a set-but-EMPTY value, and this file said that case was "deliberately ignored" because the `unset` below the refusal covered it — which is round 10's mistake restated, since the unset fixes one process and the rest of the gate runs in your shell. So `GIT_DIR= <the gate>` passed the check and the vendor leg inherited it. Empty is not equivalent to unset and it is not harmless: measured 2026-09-01, `GIT_DIR=''` gives `fatal: not a git repository: ''` at exit **128** and `GIT_WORK_TREE=''` gives `The empty string is not a valid path` at 128, so git *breaks* rather than reading elsewhere. `GIT_INDEX_FILE=''` is the quiet one — it does not error at all, and git reports every tracked file as `D` deleted. That contradicts round 10's own `/tmp/empty` measurement above (128, `index file smaller than expected`), which is exactly why the empty string needed its own case instead of being assumed covered by the adjacent one. Fix is `[ -n "${!v+x}" ]`: ask whether it is *set*, not whether it has content. Same family as `${VAR:-default}` in the sibling guard, and it is the third time this month an empty value has been read as an absent one.

The test half is the part worth carrying. Nine cases greped the output for the bare variable **name**, and the refusal prints `unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR` as advice on *every* refusal — so the substring was present whichever variable had actually been set, and no assertion could distinguish a refusal that names the offender from one that names nothing. Measured, not argued: strip `$poisoned` from the refusal's first line so it names nothing at all, and the bare-name form scores **green, with zero failures**; the tightened form, matching `environment: $v` after the colon, is **red on nine, one per assertion**. Nine assertions that read as coverage for four rounds and were decoration. The anchor matters as much as the needle — grep for the *sentence* the check produces, not for a token that appears in its help text.

### Appendix — round 2 in full, because it is the shape all seven share

**And it captures `git status` separately, because the first `if` form failed open.** `if git status --porcelain -uall | grep '^??'` reports the pipeline's status, which is `grep`'s. When `git status` itself fails, `grep` reads empty input and exits 1, so the `else` branch runs and the vendor leg proceeds — the guard says "clean worktree" exactly when it could not see the worktree. Verified on 2026-08-29 by running that form in a non-repository directory: it printed `fatal: not a git repository` and then took the proceed branch. CodeRabbit caught it one round after catching the missing `if`, which is the same lesson twice over: a check whose failure is indistinguishable from its success is not a check.
