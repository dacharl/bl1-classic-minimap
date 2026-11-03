"""Enforce explicit, per-file coverage and mutation floors. Missing data fails."""
import argparse
import ast
import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def coverage_errors(report, floors):
    files = {name.replace('\\', '/'): value for name, value in report['files'].items()}
    errors = []
    for name, floor in floors.items():
        if name not in files:
            errors.append(f'{name}: missing coverage')
            continue
        summary = files[name]['summary']
        for kind, covered, total in (
            ('line', summary['covered_lines'], summary['num_statements']),
            ('branch', summary['covered_branches'], summary['num_branches']),
        ):
            score = 100 * covered / total if total else 0
            print(f'{name}: {kind} coverage {score:.2f}% (minimum {floor[kind]}%)')
            if not total or score < floor[kind]:
                errors.append(f'{name}: {kind} coverage below {floor[kind]}%')
    return errors


def mutation_errors(report, floors):
    errors = []
    for name, floor in floors.items():
        result = report.get(name, {})
        total = result.get('total', 0)
        counted = sum(result.get(key, 0) for key in ('killed', 'survived', 'timeout', 'error', 'pending'))
        score = 100 * result.get('killed', 0) / total if total else 0
        print(f'{name}: mutation score {score:.2f}% (minimum {floor}%), {result}')
        if not total or counted != total or result.get('pending', 0) or result.get('error', 0):
            errors.append(f'{name}: missing, incomplete or failed mutation run')
        if score < floor:
            errors.append(f'{name}: mutation score below {floor}%')
    return errors


MOD_FOLDERS = ('sdk_mods/classic_minimap', 'sdk_mods/classic_minimap_profiler')


def literal_assignments(tree, name):
    return [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]


def declared_version(source):
    """__version__ as a literal in __init__.py, or re-exported (`from .x import NAME as __version__`) from a
    sibling module that assigns NAME a literal."""
    tree = ast.parse((source / '__init__.py').read_text(encoding='utf-8'))
    versions = literal_assignments(tree, '__version__')
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            for alias in node.names:
                if alias.asname == '__version__':
                    sibling = ast.parse((source / f'{node.module}.py').read_text(encoding='utf-8'))
                    versions += literal_assignments(sibling, alias.name)
    return versions


def mod_errors(source, root, quality):
    """Version fields agree, and every shipped .py file has coverage and mutation floors."""
    errors = []
    version = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
    if declared_version(source) != [version]:
        errors.append(f'{source.name}: mod version fields do not match')
    for path in sorted(source.rglob('*.py')):
        name = path.relative_to(root).as_posix()
        if '__pycache__' not in path.parts:
            for gate in ('coverage', 'mutation'):
                if name not in quality[gate]:
                    errors.append(f'{name}: missing {gate} threshold')
    return errors


def workflow_jobs(text):
    """Each job's lines by name, read from the two-space job keys under `jobs:` (no YAML parser in the CI tools)."""
    jobs, name = {}, None
    for line in text.split('\njobs:\n', 1)[-1].splitlines():
        match = re.fullmatch(r'  ([\w-]+):', line)
        if match:
            name = match[1]
            jobs[name] = ''
        elif name:
            jobs[name] += line + '\n'
    return jobs


def job_needs(body):
    match = re.search(r'^    needs: \[?([^\]\n]*)', body, re.M)
    return {name.strip() for name in match[1].split(',')} if match else set()


def release_gate_errors(ci, release):
    """A release must run the whole of CI, on main, before it publishes anything."""
    errors = []
    if not re.search(r'^  workflow_call:', ci, re.M):
        errors.append('ci.yml must allow workflow_call so the release workflow can run it')
    jobs = workflow_jobs(release)
    checks = {name for name, body in jobs.items() if 'uses: ./.github/workflows/ci.yml' in body}
    publish = [body for body in jobs.values() if 'gh release create' in body]
    if not checks:
        errors.append('release.yml must run ci.yml')
    if not publish or not all(job_needs(body) & checks for body in publish):
        errors.append('release.yml must not publish before ci.yml passes')
    before_checks = set().union(*(job_needs(jobs[name]) for name in checks)) if checks else set()
    if not any('refs/heads/main' in jobs.get(name, '') for name in before_checks):
        errors.append('release.yml must refuse other branches before running ci.yml')
    return errors


BUMPED_DOCS = ('docs/research/PERF_REPORT_V1.md', 'docs/plans/PLAN_V11_MCP_HANDOFF.md')  # bump_version edits these


def trigger_block(ci, event):
    match = re.search(rf'^  {event}:.*\n((?:    .*\n)*)', ci, re.M)
    return match[1] if match else ''


def ci_trigger_errors(ci):
    """Docs-only pushes skip CI, but a path filter on a PR event would leave required checks pending."""
    errors = [f'ci.yml must not filter {event} by path: required checks would stay pending'
              for event in ('pull_request', 'merge_group') if 'paths' in trigger_block(ci, event)]
    push = trigger_block(ci, 'push')
    if "- '!docs/**'" not in push:
        errors.append('ci.yml must skip docs-only pushes')
    errors += [f'ci.yml must run on pushes that change {doc}' for doc in BUMPED_DOCS if f"- '{doc}'" not in push]
    return errors


def repository_errors():
    errors = []
    quality = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['quality']
    workflows = ROOT / '.github/workflows'
    errors += release_gate_errors((workflows / 'ci.yml').read_text(encoding='utf-8'),
                                  (workflows / 'release.yml').read_text(encoding='utf-8'))
    errors += ci_trigger_errors((workflows / 'ci.yml').read_text(encoding='utf-8'))
    for folder in MOD_FOLDERS:
        errors += mod_errors(ROOT / folder, ROOT, quality)
    tree = ast.parse((ROOT / 'sdk_mods/classic_minimap/__init__.py').read_text(encoding='utf-8'))
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
           and node.func.attr == 'Invoke' for node in ast.walk(tree)):
        errors.append('Classic GFx Invoke is unsafe; use SingleArgInvokeS (PROGRESS fact 2)')
    for folder in ('sdk_mods', 'tools'):
        for path in (ROOT / folder).rglob('*.py'):
            if not {'__pycache__', 'pk'} & set(path.parts):
                compile(path.read_bytes(), str(path), 'exec')
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for name in tracked:
        if (name.startswith(('dist/', 'tools/pk/', 'pk/', 'swf/'))
                or Path(name).suffix.lower() in {'.upk', '.u', '.gfx', '.swf', '.exe', '.dll', '.sdkmod', '.dmp'}):
            errors.append(f'Game/build binary is tracked: {name}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=['repository', 'coverage', 'mutation'])
    args = parser.parse_args()
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['quality']
    if args.check == 'repository':
        errors = repository_errors()
    elif args.check == 'coverage':
        errors = coverage_errors(json.loads((ROOT / 'dist/ci/coverage.json').read_text()), config['coverage'])
    else:
        errors = mutation_errors(json.loads((ROOT / 'dist/ci/mutations.json').read_text()), config['mutation'])
    if errors:
        raise SystemExit('\n'.join(errors))


if __name__ == '__main__':
    main()
