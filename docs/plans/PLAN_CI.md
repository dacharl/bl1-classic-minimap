# Source-only CI (2026-10-24)

## Evidence and constraints

- The existing suites decode the built movie, but all map geometry in their interpreter is already represented by mock clips. `swfbuild.build` accepts byte strings; it can build a synthetic movie containing empty shapes and independent native-contract stubs, then run both suites without dropping assertions.
- Real HUD and status-menu input movies contain game assets. They remain local, as required by AGENTS. Synthetic inputs cannot validate copied game code, real art, package relocation or Scaleform behavior.
- Ruff's `F` and `E9` checks catch Python correctness problems without a broad style rewrite. Initial findings were nine unused imports/variables. The active code has no complete SDK typing stubs, so strict static type checking is deferred.
- Coverage.py can record line and branch counts separately. Baselines measured on Windows/Python 3.11: mod 89.76/82.31%, assembler 81.25/78.03%, movie builder 97.10/80.30%, packager 94.12/83.33%. Floors belong to each file, with missing data treated as failure.
- Cosmic Ray supports the existing script test command. Its default summary counts some non-test outcomes as kills; the repository gate instead requires a normal worker and a killed test, and counts timeouts as undetected. Every default mutant in the shipped Python mod and SDK packager is executed, without sampling or excluding uncovered lines. Movie-builder/assembler mutations are outside this initial mutation scope; both have line/branch gates and their output runs through the AS interpreter.
- Official references: [Ruff rule selection](https://docs.astral.sh/ruff/linter/), [Coverage reporting](https://coverage.readthedocs.io/en/latest/commands/cmd_reporting.html), [Cosmic Ray](https://cosmic-ray.readthedocs.io/en/latest/tutorials/intro/index.html), [actionlint](https://github.com/rhysd/actionlint/blob/main/docs/usage.md).

## Implementation

### Automatic workers (2026-10-24)

Evidence: unit checks previously ran serially inside `test_ci.py`; mutation CI explicitly selected four workers and the local default capped CPU detection at four. The local Python 3.13 installation reports eight available CPUs. A subprocess regression reproduced Python 3.13's temporary-directory weakref cleanup running before the multiprocessing finalizer left the worker directory.

Use a shared CPU-based worker selector with `auto` as the default and positive integer overrides. Run independent unittest cases in separate processes and combine separate coverage files. Split the existing movie/mod wrapper into independent cases without removing assertions. Keep the mutation test command serial within each isolated worker to avoid nested pools. Give worker cleanup one finalizer. Verify actual overlapping test processes, child-failure exit status, CPU fallback/overrides, clean worker shutdown, unchanged coverage and both real-movie suites; run all mutants with automatic workers. CI and documented commands must use the same defaults.

1. Keep test-first changes at the established built-movie and mod-hook boundaries. Add an asset-free fixture plus SDK archive tests. Check quality-gate failure cases independently.
2. Run lint and repository checks, then source-only tests with per-file coverage floors on Ubuntu/Python 3.11, Windows/Python 3.11, and Ubuntu/Python 3.13.
3. Run all mod/packager mutants on Ubuntu/Python 3.11, after ordinary checks pass. Use isolated source copies for workers, disable bytecode caches, require a passing baseline and save survivor diffs. Enforce per-file mutation floors from pyproject.toml.
4. Trigger on pushes to main (including merges), pull requests targeting main, merge-queue checks and manual dispatch. CI uses read-only repository permissions and uploads only JSON/XML quality reports, never game files or local dist contents.
5. Use actionlint for workflow expressions/shell syntax, check Python syntax and matching version fields, reject tracked game/build binaries, and check installed tool dependency consistency. Pin CI tool versions. Keep the real-movie offline suites and in-game checks as local release prerequisites.

## Limits and follow-up

The probe and one-off reverse-engineering utilities are linted and syntax-checked but have no coverage or mutation guarantee. The stubs model the documented engine quirks, not a full engine. Branch protection must be configured on GitHub to require the CI jobs; a workflow file alone cannot enforce merge policy. Hosted Linux/Python 3.13 execution remains pending until the workflow is pushed.
