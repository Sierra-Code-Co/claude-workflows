---
name: writing-check
description: Check a draft for stock AI phrasing and formulaic structure before a person reads it (emails, client documents, handouts, presenter notes). Runs a phrase list and slop-guard where scripts can run, and applies the same rules by reading where they cannot. Use before any draft goes out, and when asked to make writing plainer.
license: MIT
compatibility: Scripts need bash, grep and python3 3.11 or newer. Without them, follow the rules in this file by reading.
metadata:
  author: Sierra Code Co.
  version: "1.0"
  source: https://github.com/Sierra-Code-Co/claude-workflows
---

# Writing check

A style check for plain writing. It flags wording and structure that readers have learned to associate with chatbot output, so a person can fix them before sending. It is not a detector of AI authorship: people write these phrases too, and passing the check says nothing about who wrote a text.

## Three layers, one set of rules

1. **Phrase list** (`banned-phrases.txt`, run by `scripts/prose-lint.sh`). About 230 patterns: a hit is a hit. Use this wherever bash and grep run.
2. **slop-guard** (`vendor/slop-guard/slop-guard.pyz`, MIT, by Eric W. Tramel). Scores structure from 0 to 100: bullet runs, setup-then-reveal, "X, not Y" pairs, colon density, repeated phrases. Needs python3 3.11 or newer and nothing else. `scripts/prose-check.sh` runs both layers.
3. **Reading**. Where scripts cannot run, apply the rules in the next two sections yourself, line by line, and report what you found in the same form: the line, the rule, a plainer rewrite.

The scripts and this file describe the same rules. When the phrase list changes, update the categories below in the same change.

## Running it

From this skill's folder:

```bash
scripts/prose-check.sh draft.txt            # both layers; pass mark 80 for prose and email
scripts/prose-check.sh handout.html -t 60   # step-by-step handouts: labels and repeated file names cost points
scripts/prose-lint.sh draft.txt names.txt   # phrase list only; names.txt holds names that must not appear
```

HTML is reduced to its visible text first, so comments, CSS and scripts are not checked.

Exit codes: 0 pass, 1 flagged, 2 the check itself could not run (missing or empty file, broken phrase list, no usable Python). Treat 2 as "not checked", never as clean.

Fix what reads as a tell and run it again. Some flags are fine to keep: a contrast that stops a real mistake ("the big box below, not the description box"), a file name repeated on purpose in a handout, a footer repeated on every page.

## Rules for reading (layer 3)

### Phrase categories

- **Framing devices**: announcing what follows instead of saying it. "Five things you may want to know:", "Two blanks only you can fill", "One more thing", "Here's the thing", "The short version", "The real question", "Worth noting", "Bottom line", "To be clear", "In short".
- **Stage directions**: telling a presenter how to deliver a line. "Name them once.", "Say it plainly.", "That is the lesson:", "Let it land.", "Nobody asked it to count."
- **Payoff lines**: "That is the difference between X and Y.", "Why this matters.", "This matters.", "It comes down to", "Ultimately".
- **Reveal pairs**: "Not a detail. A design decision.", "It isn't X. It's Y.", "It's not X, it's Y", "not only X but Y".
- **Inflated vocabulary**: leverage, unlock, robust, seamless, crucial, pivotal, delve, tapestry, landscape, journey, paradigm, showcase, underscore, foster, empower, streamline, groundbreaking, cutting-edge.
- **Puffery and avoided "is"**: "serves as", "stands as", "plays a vital role", "marks a shift", "setting the stage".
- **Hedges and weasels**: "could potentially", "studies show", "experts suggest", "many believe", "some argue".
- **Chatbot correspondence**: "I hope this helps", "Great question", "Feel free to", "Would you like me to", "Shall I", "As an AI".
- **Plumbing**: script or notes file names (.py, .md, .json, .sh, .yml) in text a reader sees. Document file names (.docx, .xlsx, .pdf) are fine.
- **Punctuation**: em dashes, spaced en dashes and spaced double hyphens used as dashes; double spaces between words.

Some words are tells only in some senses (key, highlight, valuable, matters, comprehensive, ecosystem, "in addition", "let me know if"). Read for those; do not flag them on sight.

### Structure (slop-guard's rules, in plain words)

- **Setup then reveal.** A short sentence that sets up a point, then another that delivers it ("It is not a tool. It is a habit."). State the point once.
- **Contrast pairs.** "X, not Y" used for effect rather than to stop a real mistake.
- **Pithy fragments.** Short verbless sentences used as punchlines ("Full stop.", "Every time.").
- **Closing aphorism.** A paragraph or document that ends on a quotable one-liner. End on the last fact instead.
- **Bullet runs.** Six or more bullet lines in a row, or most of a message in bullets. Write paragraphs; keep lists for steps and options.
- **Bold-term bullets and bold headers** on every item.
- **Triads.** Lists of exactly three, again and again.
- **Colon density.** Colons that announce an elaboration ("Here is the plan: ..."). In a short note one is enough to stand out.
- **Same-length sentences.** Five or more sentences in a row of nearly the same length. Vary them.
- **Repeated phrases.** The same three-to-five-word phrase several times in one piece.
- **Extreme sentences.** One very long run-on, or a string of very short ones.
- **Placeholders and disclosure.** "[insert name]", "2026-XX-XX", "as of my last update".

Short texts are judged harshly: penalties scale with length, so one colon can sink a 65-word note. A 795-word email with 12 of 20 lines as bullets scored 55; the same content as paragraphs scored 100.

## Adding a tell

Add a pattern to `banned-phrases.txt` under the right section, with the date and where it was seen (no client names). Add a red and a green example to the tests. If it belongs to a category above, nothing else changes; if it is a new kind of tell, add it to the list above.

## Related

`client-doc` (house-style PDFs for clients) is a separate skill, not yet published; it runs this check as one of its steps.
