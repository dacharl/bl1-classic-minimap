# CI checks

**Continuous, blocking checks:** `.github/workflows/ci.yml` runs on pushes to `main` (including merged PRs), PRs targeting `main`, merge-queue events and manual dispatch. It has two jobs: **lint** (Ruff, dependency consistency, repository checks, actionlint) and **unit tests with per-file line and branch coverage floors**. These and the secret scan are the only checks that run continuously; configure them as required status checks.

**Secret scan:** `.github/workflows/secrets.yml` runs gitleaks 8.30.1 over the **whole git history** on every push to any branch, every PR, merge-queue events and manual dispatch. It has no path filter, because a secret in a docs-only change is as public as one in code. It downloads the pinned Linux release and checks its SHA-256 (from the release's `checksums.txt`) before running it, and prints findings redacted. On a public repository, also turn on GitHub's own **secret scanning** and **push protection** (Settings → Code security; free for public repositories on personal accounts). They check against providers' token formats and block a push, which gitleaks in CI can only report after the fact (PHASE3 §3ca).

**Test matrix:** two jobs. **Windows/Python 3.14** is the game's OS and the interpreter the PythonSDK embeds (`python314.dll` in `Binaries\Plugins`). **Ubuntu/Python 3.13** is the version the local tools run on, and covers the mutation runner's POSIX process-group cleanup. Lint and mutation testing use Python 3.13. Python 3.11 was dropped in PHASE3 §3bn: nothing runs on it.

**Billable minutes:** the repository is private, so hosted runs draw on the plan's monthly Actions minutes.
- **Pushes that change only `docs/` or a root `.md` file skip CI.** The filter is on `push` alone: a path-filtered workflow leaves required checks pending, so PRs and the merge queue always run. The two docs `bump_version.py` edits still trigger CI, because the tests read them. `quality_checks.py repository` fails if either rule is removed.
- **Prefer running mutation testing locally.** One hosted run can use up to 180 minutes.
- **Batch pushes when practical.** A push runs CI once, however many commits it holds; a cancelled run still bills the time it used.
- **Keep the Windows job under a minute.** Each job is rounded up to whole minutes, and Windows minutes count double, so a 90 s Windows job bills 4 minutes and a 55 s one 2. The test jobs therefore restore the whole installed tools environment from `actions/cache` (keyed on the OS, the exact Python version and `requirements-ci.txt`) instead of reinstalling it (PHASE3 §3by). A changed requirements file installs once, runs `pip check` and saves a new cache; a restored one only checks that `python` is that environment.

**On demand:** mutation testing runs only when started by hand: **Actions → Mutation testing → Run workflow** (`.github/workflows/mutation.yml`), or locally with `tools/run_mutations.py`. A full run takes over an hour, so it is not part of continuous CI and does not block merges. Run it before raising floors, after changing the shipped mods or the packager in ways the unit tests may not catch, and before a release when practical.

**Releases:** `.github/workflows/release.yml` is started by hand from main. It refuses any other branch or tag, runs the whole of `ci.yml` through `workflow_call`, and publishes only if that passes. `quality_checks.py repository` fails if that order is removed. Before CI starts, its first job also checks the version fields, that the `v<version>` tag doesn't exist yet, and that the release has notes (`tools/release_notes.py`: `docs/release_notes/<version>.md`, else the run's `notes` input, else the run fails). The release job then packages and verifies the mod, creates the tag at the tested commit and attaches `classic_minimap.sdkmod` and `classic_minimap-changes.md` (the commits since the previous release tag, grouped by Conventional Commit type) to the GitHub release. It does not run the mutation tests or the real-movie suites, so run those locally first (AGENTS, PROGRESS).

The hosted jobs need no game installation or credentials. Reports are retained for 14 days.

## Gates

| File | Minimum line coverage | Minimum branch coverage | Minimum mutation score |
|---|---:|---:|---:|
| `sdk_mods/classic_minimap/__init__.py` | 89% | 81% | 70% |
| `sdk_mods/classic_minimap/swfmerge.py` | 90% | 80% | 70% (not yet measured) |
| `sdk_mods/classic_minimap/hudmovie.py` | 90% | 85% | 70% (not yet measured) |
| `sdk_mods/classic_minimap/swfbuild.py` | 97% | 78% | 70% (not yet measured) |
| `sdk_mods/classic_minimap/as2asm.py` | 81% | 76% | 70% (not yet measured) |
| `sdk_mods/classic_minimap/upk.py` | 88% | 70% | 70% (not yet measured) |
| `sdk_mods/classic_minimap/swfdeps.py` | 60% | 45% | 70% (not yet measured) |
| `tools/build_sdkmod.py` | 94% | 83% | 80% |
| `tools/land_branch.py` | 92% | 85% | Not gated |
| `tools/release_notes.py` | 85% | 80% | Not gated |
| `sdk_mods/classic_minimap_profiler/__init__.py` | 95% | 95% | 85% |
| `sdk_mods/classic_minimap_profiler/profiler.py` | 95% | 88% | 78% |

The builder moved into the mod in v0.13 (PLAN_V13 decision 16), so its files are shipped mod files and need both floors; the `tools/` files of the same names are wrappers and aren't gated. The mutation floors marked "not yet measured" are configured, but those files aren't in `cosmic-ray.toml`'s module list yet. The floors are configured in `pyproject.toml` and applied separately to each file. Missing reports or missing files fail. Coverage counts Python execution of the builder and assembler; it does not measure AS2 instruction coverage or actual game engine behavior.

Mutation gates cover the shipped Python mod and SDK packager, configured in `cosmic-ray.toml` and `pyproject.toml`. The runner executes every default Cosmic Ray mutant in these files, including uncovered code. A passing original suite is required first. Each worker mutates an isolated source copy. Every mutant remains in the denominator: only a normal worker with a failing test earns a kill; timeouts count as undetected, and tool errors or incomplete results fail the gate. Survivor diffs are uploaded for investigation. This is mutation detection, not an assertion that all surviving mutations are bugs; equivalent mutants can survive.

Initial Windows/Python 3.11 baseline: the mod killed 2,059 of 2,767 mutants (74.41%); the packager killed 32 of 39 (82.05%). There were no mutant timeouts or worker errors. Packager survivors include untested CLI argument handling and destination-parent creation. These remain in the denominator; strengthen those tests before raising the floor. v0.16.0 removed about 370 lines from the mod, so its score needs a fresh run.

Ruff `F`/`E9` checks run over both mods and all Python tools. Additional checks validate workflow syntax with actionlint, Python syntax, matching version fields, dependency consistency, SDK archive structure/content/cache exclusion, the absence of tracked game/build binaries, the ban on unsafe `.Invoke` calls, and coverage and mutation thresholds being configured for every shipped mod Python file. These run in the continuous lint job; the mutation scores themselves are checked only by on-demand mutation runs.

## Parallel workers

Validated locally on Windows/Python 3.13.17 with eight automatic workers: at the time, all 11 unit cases passed (there are 135 now), combined coverage cleared every existing floor, and all 2,806 mutants completed with the same scores as the initial baseline and zero timeouts, worker errors or cleanup tracebacks. Python 3.11 also passes the unit suite with a two-worker override. Hosted execution remains pending.

Both `tools/run_tests.py` and `tools/run_mutations.py` default to `--workers auto` locally and in CI. They use the CPUs available to the process (`os.process_cpu_count()` on Python 3.13+, otherwise `os.cpu_count()`), falling back to one worker when the count is unavailable. Unit workers are capped at the number of test processes; mutation workers respect Windows' 61-process pool limit. Pass `--workers N` to override the count, including `--workers 1` for serial runs.

The default unit run starts one Python process per suite, and one per case for `test_ci.SourceChecks`, whose cases run the real mod's `main()` (it works only once per process). Explicit test IDs get one process per case. A process costs about 0.5 s under coverage, so per-case isolation took about 90 s at two workers against about 50 s now, with identical coverage (PHASE3 §3bl). `--coverage` erases stale coverage, writes separate child data files and combines them before the existing per-file gates run. Coverage runs should not share an output directory concurrently. The default run starts the slowest suites (`test_runners`, `test_land`, `test_workflow`) first, so the short processes fill the gaps (PHASE3 §3by). `--durations N` adds each process's wall time to its PASS line and lists its N slowest tests (Python 3.12+); CI uses `--durations 5`. Optional positional unittest IDs select a subset of tests. Each process has a 240 s timeout (`--timeout`): the slowest suite takes about 35 s locally, and a hung process then fails with its output instead of the job being cancelled at 10 minutes with none (PHASE3 §3bp).

Mutation workers retain isolated source copies and run `tools/test_mutants.py` serially inside each worker, avoiding nested CPU pools. It runs `test_ci.py` and then `test_profiler.py`, each in its own process, because both import the real core with stubbed SDK modules (once per process). With two suites per mutant the per-mutant timeout is 20 s. Hang safety: on timeout Cosmic Ray kills the test command (its process group on POSIX, only the direct process on Windows) and then waits for the output pipe. A suite that outlives the command keeps that pipe open and stalls the worker permanently. This happened twice:
- **At 1,200 of 3,866:** the suites survived the killed venv launcher.
- **At 3,850:** a mutant spun inside one C call, holding the GIL, so the in-process watchdog never ran.

`test_mutants.py` therefore makes the operating system clean up:
- **POSIX:** suites stay in the command's process group, which `killpg` covers.
- **Windows:** suites run on the base interpreter inside a kill-on-close job object, so they die when the command dies, however it dies.
- **Extra layers:** a 25 s budget kills a suite's whole tree while the command is alive (`taskkill /T` on Windows; on POSIX every descendant from a `ps` snapshot, since `proc.kill()` alone orphaned grandchildren, PHASE3 §3bp), and `tools/watchdog_run.py` ends suites stuck in Python code.

Cosmic Ray still records such mutants as timeouts (undetected). The Windows path is verified locally with Cosmic Ray's own kill function; the POSIX path runs in CI's Ubuntu jobs. `run_mutations.py --modules <paths>` limits a local run to some configured files (for measuring one file; CI always runs all of them, and the gate then sees only the selected files). Their Windows cleanup has one finalizer that leaves the temporary working directory before removing it, including on Python 3.13. Mutation scope, score denominators and coverage floors are unchanged.

## Local commands

**Commit hooks** (`.pre-commit-config.yaml`, pre-commit 4.7.0 from `requirements-dev.txt`) run the lint job's checks before each commit, so a commit can't pass locally and then fail lint in CI (PHASE3 §3bz):

| Hook | Files | Same as CI |
|---|---|---|
| `gitleaks` (gitleaks v8.30.1) | staged changes | the secret scan in `secrets.yml`, same version and rules; CI also scans the whole history |
| `ruff-check` (ruff-pre-commit v0.17.2) | Python | `ruff check`, same version and `pyproject.toml` rules |
| `actionlint` (actionlint-py 1.7.12.25 with shellcheck-py) | `.github/workflows/*.yml` | the `rhysd/actionlint:1.7.12` image, ShellCheck included |
| `quality_checks.py repository` | always | the repository checks |
| `check-json`, `check-toml` | JSON (minus the deliberately invalid `invalid-*` report fixtures), TOML | syntax only; CI's tests read them |
| `check-added-large-files --maxkb=300`, `check-merge-conflict`, `check-case-conflict`, `git diff --cached --check` | staged files | guards for game files and commit hygiene (AGENTS) |

`quality_checks.py repository` fails if the hooks' ruff or actionlint differ from `requirements-ci.txt` and `ci.yml`, or their gitleaks from `GITLEAKS_VERSION` in `secrets.yml` (update its `GITLEAKS_SHA256` with it). The gitleaks hook builds from source with Go; pre-commit downloads a Go toolchain on its first run when none is installed. For a manual full-history scan, gitleaks 8.30.1 is in `C:\Users\Charles\Tools\gitleaks-8.30.1\` on this PC: `gitleaks git . --redact -v --log-opts=--all`. Install with `pip install -r requirements-dev.txt` and `pre_commit install --allow-missing-config`: the hook lives in the shared `.git/hooks`, and the option lets commits on older branches without the config go through. The first run downloads each hook's environment. prek, a Rust reimplementation, reads the same config if pre-commit ever becomes too slow.

From the repository root, create a virtual environment and install the pinned tools:

```powershell
python -I -m venv .venv
.venv/Scripts/python.exe -I -m pip install -r requirements-ci.txt
.venv/Scripts/python.exe -I -m pip check
.venv/Scripts/python.exe -I -m ruff check sdk_mods tools
.venv/Scripts/python.exe -I tools/quality_checks.py repository
.venv/Scripts/python.exe -B -I tools/run_tests.py --coverage
.venv/Scripts/python.exe -I -m coverage report
.venv/Scripts/python.exe -I -m coverage json
.venv/Scripts/python.exe -I tools/quality_checks.py coverage
# On demand (over an hour):
.venv/Scripts/python.exe -B -I tools/run_mutations.py
.venv/Scripts/python.exe -I tools/quality_checks.py mutation
```

`dist/ci/` contains local reports and the mutation session database. The workflow uploads only the named quality report files. Use actionlint 1.7.12 to check `.github/workflows/*.yml` before committing any workflow edit (`actionlint -no-color .github/workflows/*.yml`; on this PC it is `C:\Users\Charles\Tools\actionlint-1.7.12\actionlint.exe`). GitHub rejects an invalid workflow file outright, so no job runs to report it (PHASE3 §3by). The hosted job uses actionlint's official Docker image with ShellCheck; a local run without ShellCheck skips the shell checks.

`tools/ci_fixture.py` independently authors empty sprites and five native-contract stubs, then passes them through the real movie builder. Both existing movie/mod suites run against that result without skipped assertions. This catches source logic and bytecode generation regressions. It does not verify original/copied game functions, artwork, UPK relocation, runtime Scaleform compatibility or in-game behavior. Run both original suites against your locally built game movie before installing/releasing, as described in PROGRESS.

The research tools have lint/syntax checks only. Strict SDK type checks and mutation gates for the movie builder/assembler are future work. Configure required status checks in GitHub branch protection after the first hosted run.

`test_workflow.WorkflowChecks` is part of the default unit run. It exercises the maintenance CLIs
against temporary source trees, independently authored movie/package inputs, logs and fake game
folders. It also injects process-query and file-replacement outcomes at the OS boundary to check
running-game refusal and rollback. The install scenarios run `install.main` in-process with the process
query injected, so they pass whether or not the game is open (PHASE3 §3bx). It never installs into the user's
game. See [TOOLS.md](TOOLS.md).
