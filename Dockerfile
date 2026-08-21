# review-plan-v2 — pinned toolchain image.
#
# STATUS 2026-08-16: BUILT AND VERIFIED on linux/aarch64 — build exit 0, all six
# version pins AND all ten artifact digests asserted at build time, and **884
# tests run by the build itself** (T005f), matching host and CI exactly. Both
# negative cases proven against a real build, not reasoned about: a wrong digest
# exits 1 with `DIGEST MISMATCH`, an empty digest exits 1 with `REFUSING`, and a
# deliberately failing test exits 1 rather than producing an image.
#
# This header previously read "WRITTEN BUT NOT BUILT ... treat it as a proposal",
# which stayed put through several successful builds while comments further down
# described those builds in the past tense. A status line that contradicts the
# file it heads is worse than no status line, and it was flagged by this repo's
# own reviewer rather than noticed by its author.
#
# WHY AN IMAGE AND NOT JUST pyproject.toml:
# This harness shells out to eight external binaries. A dependency tree pins the
# Python half and says nothing about the other half, so two runs on two machines
# can disagree because one had actionlint 1.7.12 and the other 1.6.x — and the
# run reports a finding count either way, with no signal that the toolchains
# differed. Comparing those runs is the censored-measurement mistake in a
# different costume (Principle IV). Every version below is pinned to what was
# actually installed when this portfolio's measurements were taken.
#
# DIGESTS PINNED 2026-08-16 (T005d). Every downloaded artifact and both base
# images are now content-addressed, so a re-tagged release fails the build
# instead of silently changing the toolchain. Provenance is NOT uniform, and the
# difference is recorded rather than smoothed over:
#
#   cross-verified against the vendor's own published checksums file
#     yq (checksums + checksums_hashes_order), gitleaks and actionlint
#     (*_checksums.txt) — 6 of 10 artifact digests, all matched exactly.
#   trust-on-first-use, computed from the 2026-08-16 download
#     shellcheck and ast-grep publish no checksums file for these releases
#     (asset lists checked, not assumed). These digests pin against a
#     re-tagged release from now on, which is the point, but they are not
#     independent confirmation of what upstream intended to publish.
#
# Base images are pinned to the multi-arch INDEX digest, so amd64 and arm64
# both still resolve from one pin. Refresh with:
#   docker buildx imagetools inspect <image> --format '{{.Manifest.Digest}}'

# Node is needed only for markdownlint-cli. Copying it from the official image
# avoids piping a vendor setup script into a shell; both stages are bookworm, so
# glibc matches.
FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS node

FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134

ARG YQ_VERSION=4.53.2
ARG GITLEAKS_VERSION=8.30.1
ARG ACTIONLINT_VERSION=1.7.12
ARG AST_GREP_VERSION=0.45.1
ARG MARKDOWNLINT_CLI_VERSION=0.48.0
ARG SHELLCHECK_VERSION=0.11.0

# Per-arch sha256 of each release artifact. A version ARG and its digest ARGs
# must be changed together; the build fails loudly if they disagree, which is
# the entire point — bumping the version alone now breaks rather than silently
# installing something unverified.
ARG SHELLCHECK_SHA256_AMD64=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
ARG SHELLCHECK_SHA256_ARM64=12b331c1d2db6b9eb13cfca64306b1b157a86eb69db83023e261eaa7e7c14588
ARG YQ_SHA256_AMD64=d56bf5c6819e8e696340c312bd70f849dc1678a7cda9c2ad63eebd906371d56b
ARG YQ_SHA256_ARM64=03061b2a50c7a498de2bbb92d7cb078ce433011f085a4994117c2726be4106ea
ARG GITLEAKS_SHA256_AMD64=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
ARG GITLEAKS_SHA256_ARM64=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080
ARG ACTIONLINT_SHA256_AMD64=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
ARG ACTIONLINT_SHA256_ARM64=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6
ARG AST_GREP_SHA256_AMD64=76fb6555be6734fb5057dba8d2fb756430f374bb9e1af694cf1ce00e13238d63
ARG AST_GREP_SHA256_ARM64=9ee7ec49aada3dc05135d21977af089a33fc3154ada25bab102daca90b5098f2

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# jq and git come from Debian and are deliberately NOT pinned: they are
# utilities the shell wrapper calls, not gates, so their version cannot change
# a finding. Every tool that CAN change a finding is pinned below.
#
# shellcheck was in this apt list in the first draft. The first build exposed
# why that was wrong: bookworm ships 0.9.0 while the host measured 0.11.0, and
# shellcheck gained checks between them — so the 180-finding baseline recorded
# for T063b would not reproduce inside the very image built to make runs
# reproducible. It is now pinned to the release binary like the rest. The build
# succeeded, check_deps printed "ok", and every binary was present; nothing but
# an explicit version comparison would have caught it.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      ca-certificates \
      curl \
      git \
      jq \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# Each artifact is verified BEFORE it is unpacked, never after: `tar -x` on an
# unverified archive has already written to the filesystem by the time a later
# check could object. `test_verification_precedes_unpacking` asserts that
# ordering rather than trusting this comment.
#
# The empty-digest branch is not defensive padding. `sha256sum -c` on an empty
# hash is a FORMAT error, whose exit code is easy to mistake for a mismatch, so
# `--build-arg YQ_SHA256_AMD64=` would otherwise switch verification off while
# every line of build output stayed identical.
#
# Comments live ABOVE the RUN, matching the rest of this file. Docker's parser
# does strip `#` lines inside a continuation — the builds prove it — but relying
# on that is a subtlety no reader should have to know, and review flagged it.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) yq_arch=amd64; gl_arch=x64;   al_arch=amd64; sg_arch=x86_64-unknown-linux-gnu;  sc_arch=x86_64; \
             sc_sha="${SHELLCHECK_SHA256_AMD64}"; yq_sha="${YQ_SHA256_AMD64}"; \
             gl_sha="${GITLEAKS_SHA256_AMD64}";   al_sha="${ACTIONLINT_SHA256_AMD64}"; \
             sg_sha="${AST_GREP_SHA256_AMD64}" ;; \
      arm64) yq_arch=arm64; gl_arch=arm64; al_arch=arm64; sg_arch=aarch64-unknown-linux-gnu; sc_arch=aarch64; \
             sc_sha="${SHELLCHECK_SHA256_ARM64}"; yq_sha="${YQ_SHA256_ARM64}"; \
             gl_sha="${GITLEAKS_SHA256_ARM64}";   al_sha="${ACTIONLINT_SHA256_ARM64}"; \
             sg_sha="${AST_GREP_SHA256_ARM64}" ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    \
    verify() { \
      test -n "$1" || { echo "REFUSING: empty sha256 for $2" >&2; exit 1; }; \
      echo "$1  $2" | sha256sum -c - || { echo "DIGEST MISMATCH: $2" >&2; exit 1; }; \
    }; \
    \
    curl -fsSL -o /tmp/shellcheck.tar.xz \
      "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.${sc_arch}.tar.xz"; \
    verify "$sc_sha" /tmp/shellcheck.tar.xz; \
    tar -xJf /tmp/shellcheck.tar.xz -C /tmp; \
    mv "/tmp/shellcheck-v${SHELLCHECK_VERSION}/shellcheck" /usr/local/bin/shellcheck; \
    chmod +x /usr/local/bin/shellcheck; \
    rm -rf /tmp/shellcheck.tar.xz "/tmp/shellcheck-v${SHELLCHECK_VERSION}"; \
    \
    curl -fsSL -o /tmp/yq \
      "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${yq_arch}"; \
    verify "$yq_sha" /tmp/yq; \
    mv /tmp/yq /usr/local/bin/yq; \
    chmod +x /usr/local/bin/yq; \
    \
    curl -fsSL -o /tmp/gitleaks.tar.gz \
      "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gl_arch}.tar.gz"; \
    verify "$gl_sha" /tmp/gitleaks.tar.gz; \
    tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks; \
    \
    curl -fsSL -o /tmp/actionlint.tar.gz \
      "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${al_arch}.tar.gz"; \
    verify "$al_sha" /tmp/actionlint.tar.gz; \
    tar -xzf /tmp/actionlint.tar.gz -C /usr/local/bin actionlint; \
    \
    curl -fsSL -o /tmp/ast-grep.zip \
      "https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-${sg_arch}.zip"; \
    verify "$sg_sha" /tmp/ast-grep.zip; \
    python3 -c "import zipfile,sys; zipfile.ZipFile('/tmp/ast-grep.zip').extractall('/usr/local/bin')"; \
    chmod +x /usr/local/bin/ast-grep /usr/local/bin/sg 2>/dev/null || true; \
    \
    rm -f /tmp/gitleaks.tar.gz /tmp/actionlint.tar.gz /tmp/ast-grep.zip

RUN npm install -g "markdownlint-cli@${MARKDOWNLINT_CLI_VERSION}" \
 && npm cache clean --force

WORKDIR /work
COPY pyproject.toml ./
COPY scripts/ ./scripts/
# tests/ ships too, so the image can verify itself without a bind mount. An
# image whose suite can only be run by mounting the source over it has not
# really been shown to work.
COPY tests/ ./tests/
COPY rules/ ./rules/
# Authoritative contracts, so the schema-drift check runs inside the image too.
COPY specs/003-gate-portfolio/contracts/ ./specs/003-gate-portfolio/contracts/
# Same reasoning, second instance: the ast-grep version pin lives in BOTH this
# file and the CI workflow, and a test compares them. Shipping the two config
# files (~10KB) is what lets that comparison run everywhere. The first build
# after that test was written failed here — a test that could only pass on a
# dev laptop, which is the identical defect the contracts COPY above exists to
# fix, written hours after recording that lesson.
COPY Dockerfile ./
COPY .github/workflows/tests.yml ./.github/workflows/tests.yml
RUN pip install --no-cache-dir --disable-pip-version-check -e ".[dev]"

# Fail the BUILD if the toolchain is incomplete or has drifted off its pins,
# rather than at run time inside a review where a missing binary reads as "that
# analyzer found nothing".
#
# check_deps alone is NOT sufficient here and the first build proved it: it
# returns 0 whenever the three REQUIRED tools are present, so it printed "ok"
# over a shellcheck two minor versions off its pin. A check whose pass condition
# is narrower than the claim it is used to support is the failure mode this repo
# is named after. The version assertions below are the actual check; check_deps
# stays for its own narrower purpose.
#
# The match is anchored on BOTH sides, and that took three passes to get right —
# each pass found by this repo's own reviewer, which is the argument for the
# reviewer.
#   pass 1: `*"$want"*`      — "0.45.10" satisfies a pin of "0.45.1"
#   pass 2: right-anchored   — "14.53.2" satisfies a pin of "4.53.2"
#   pass 3: both sides       — the version must be delimited by something that
#                              cannot continue a version number, on each end.
# Four cases because the version can sit at either boundary of the string.
RUN set -eux; \
    python3 -m review_plan_v2.check_deps; \
    assert_version() { \
      name="$1"; want="$2"; got="$3"; \
      case "$got" in \
        "$want") echo "  ok  $name $want" ;; \
        "$want"[!0-9.]*) echo "  ok  $name $want" ;; \
        *[!0-9.]"$want") echo "  ok  $name $want" ;; \
        *[!0-9.]"$want"[!0-9.]*) echo "  ok  $name $want" ;; \
        *) echo "PIN DRIFT: $name expected $want, got: $got" >&2; exit 1 ;; \
      esac; \
    }; \
    assert_version yq           "${YQ_VERSION}"               "$(yq --version)"; \
    assert_version gitleaks     "${GITLEAKS_VERSION}"         "$(gitleaks version)"; \
    assert_version actionlint   "${ACTIONLINT_VERSION}"       "$(actionlint --version)"; \
    assert_version ast-grep     "${AST_GREP_VERSION}"         "$(ast-grep --version)"; \
    assert_version markdownlint "${MARKDOWNLINT_CLI_VERSION}" "$(markdownlint --version)"; \
    assert_version shellcheck   "${SHELLCHECK_VERSION}"       "$(shellcheck --version)"; \
    echo "toolchain pinned and verified"

# Run the suite at BUILD time (T005f). Until now `tests/` shipped and nothing
# executed it during the build, so container parity was only ever checked by
# hand — and both container-only defects found so far would have been build
# failures instead of manual discoveries:
#
#   * `test_contract_file_is_valid_json_schema` read `specs/`, which
#     .dockerignore excluded, so it could only ever pass on a dev laptop;
#   * the pin-drift test's `FileNotFoundError: /work/Dockerfile`.
#
# Both were found by someone remembering to run pytest inside a container. That
# is not a gate, it is a habit, and the difference is the subject of this spec.
#
# `-p no:randomly` is NOT set and `-q` is deliberate: this must be the same
# invocation CI runs, or the two can disagree and the disagreement is the signal
# (a container-only failure is exactly what this catches). Costs ~30s on a
# ~4-minute build.
RUN python -m pytest tests/ -q

ENTRYPOINT ["review-plan-v2"]
