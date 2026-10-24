# CI checks

`.github/workflows/ci.yml` runs on pushes to `main` (including merged PRs), PRs targeting `main`, merge-queue events and manual dispatch. The hosted jobs need no game installation or credentials. Reports are retained for 14 days.

## Gates

| File | Minimum line coverage | Minimum branch coverage | Minimum mutation score |
|---|---:|---:|---:|
| `sdk_mods/classic_minimap/__init__.py` | 89% | 81% | 70% |
| `tools/as2asm.py` | 81% | 76% | Not gated |
| `tools/swfbuild.py` | 97% | 78% | Not gated |
| `tools/build_sdkmod.py` | 94% | 83% | 80% |

The floors are configured in `pyproject.toml` and applied separately to each file. Missing reports or missing files fail. Coverage counts Python execution of the builder and assembler; it does not measure AS2 instruction coverage or actual game engine behavior.

Mutation gates cover the shipped Python mod and SDK packager, configured in `cosmic-ray.toml` and `pyproject.toml`. The runner executes every default Cosmic Ray mutant in these files, including uncovered code. A passing original suite is required first. Each worker mutates an isolated source copy. Every mutant remains in the denominator: only a normal worker with a failing test earns a kill; timeouts count as undetected, and tool errors or incomplete results fail the gate. Survivor diffs are uploaded for investigation. This is mutation detection, not an assertion that all surviving mutations are bugs; equivalent mutants can survive.

Initial Windows/Python 3.11 baseline: the mod killed 2,059 of 2,767 mutants (74.41%); the packager killed 32 of 39 (82.05%). There were no mutant timeouts or worker errors. Packager survivors include untested CLI argument handling and destination-parent creation. These remain in the denominator; strengthen those tests before raising the floor.

Ruff `F`/`E9` checks run over both mods and all Python tools. Additional checks validate workflow syntax with actionlint, Python syntax, matching version fields, dependency consistency, SDK archive structure/content/cache exclusion, the absence of tracked game/build binaries, the ban on unsafe `.Invoke` calls, and thresholds for every shipped mod Python file. These checks run before the slower mutation job.

## Local commands

From the repository root, create a virtual environment and install the pinned tools:

```powershell
python -I -m venv .venv
.venv/Scripts/python.exe -I -m pip install -r requirements-ci.txt
.venv/Scripts/python.exe -I -m pip check
.venv/Scripts/python.exe -I -m ruff check sdk_mods tools
.venv/Scripts/python.exe -I tools/quality_checks.py repository
.venv/Scripts/python.exe -I tools/test_quality.py
.venv/Scripts/python.exe -B -I -m coverage run tools/test_ci.py
.venv/Scripts/python.exe -I -m coverage report
.venv/Scripts/python.exe -I -m coverage json
.venv/Scripts/python.exe -I tools/quality_checks.py coverage
.venv/Scripts/python.exe -B -I tools/run_mutations.py --workers 4
.venv/Scripts/python.exe -I tools/quality_checks.py mutation
```

`dist/ci/` contains local reports and the mutation session database. The workflow uploads only the named quality report files. Use actionlint 1.7.12 to check `.github/workflows/*.yml`; the hosted job uses its official Docker image with ShellCheck.

`tools/ci_fixture.py` independently authors empty sprites and five native-contract stubs, then passes them through the real movie builder. Both existing movie/mod suites run against that result without skipped assertions. This catches source logic and bytecode generation regressions. It does not verify original/copied game functions, artwork, UPK relocation, runtime Scaleform compatibility or in-game behavior. Run both original suites against your locally built game movie before installing/releasing, as described in PROGRESS.

The obsolete probe and research tools have lint/syntax checks only. Strict SDK type checks and mutation gates for the movie builder/assembler are future work. Configure required status checks in GitHub branch protection after the first hosted run.
