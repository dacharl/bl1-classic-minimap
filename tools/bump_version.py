"""Synchronize core/profiler versions and regenerate performance contract fixtures.

Example: python -I tools/bump_version.py 0.10.3 --profiler-version 0.1.3
"""
import argparse
import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')


def version(value):
    if not VERSION.fullmatch(value):
        raise argparse.ArgumentTypeError('version must be three non-negative integers (e.g. 0.10.3)')
    return value


def assignment(text, name, value):
    result, count = re.subn(rf'(?m)^({re.escape(name)}\s*=\s*)["\'][^"\']+["\']',
                            lambda m: m[1] + '"' + value + '"', text)
    if count != 1:
        raise ValueError(f'expected exactly one {name} assignment, found {count}')
    return result


def bump(repo, core_version, profiler_version, dry_run=False):
    repo = Path(repo).resolve()
    core = repo / 'sdk_mods/classic_minimap'
    profiler = repo / 'sdk_mods/classic_minimap_profiler'
    files = [core / '__init__.py', core / 'pyproject.toml', profiler / 'profiler.py',
             profiler / 'pyproject.toml', repo / 'docs/research/PERF_REPORT_V1.md',
             repo / 'docs/plans/PLAN_V11_MCP_HANDOFF.md']
    original = {p: p.read_bytes() for p in files}
    texts = {p: b.decode('utf-8-sig') for p, b in original.items()}
    source = texts[profiler / 'profiler.py']
    old_prof = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PROFILER_VERSION'
                                                        for t in n.targets))
    texts[core / '__init__.py'] = assignment(texts[core / '__init__.py'], '__version__', core_version)
    texts[core / 'pyproject.toml'] = assignment(texts[core / 'pyproject.toml'], 'version', core_version)
    source = assignment(source, 'PROFILER_VERSION', profiler_version)
    match = re.search(r'(?m)^SUPPORTED_CORE_VERSIONS\s*=\s*(\([^\n]*?\))', source)
    if not match:
        raise ValueError('missing single-line SUPPORTED_CORE_VERSIONS tuple')
    supported = ast.literal_eval(match[1])
    if not isinstance(supported, tuple) or not all(isinstance(v, str) for v in supported):
        raise ValueError('invalid SUPPORTED_CORE_VERSIONS')
    if core_version not in supported:
        supported += (core_version,)
    literal = '(' + ', '.join('"' + v + '"' for v in supported) + ',)'
    texts[profiler / 'profiler.py'] = source[:match.start(1)] + literal + source[match.end(1):]
    texts[profiler / 'pyproject.toml'] = assignment(texts[profiler / 'pyproject.toml'], 'version', profiler_version)
    contract, handoff = files[-2:]
    texts[contract], count = re.subn(
        r'(versions \d+\.\d+\.\d+\u2013)\d+\.\d+\.\d+(; the fixtures come from )\d+\.\d+\.\d+',
        lambda m: m[1] + profiler_version + m[2] + profiler_version, texts[contract], count=1)
    if count != 1:
        raise ValueError('missing contract producer version line')
    texts[handoff], count = re.subn(r'(produced by profiler )\d+\.\d+\.\d+',
                                   lambda m: m[1] + profiler_version, texts[handoff], count=1)
    if count != 1:
        raise ValueError('missing handoff producer version line')
    texts[handoff] = re.sub(r'\(current `\d+\.\d+\.\d+`\)', '(current `' + profiler_version + '`)', texts[handoff], count=1)
    match = re.search(r'allow ([\d.,\sand]+)\)\.', texts[handoff])
    if not match:
        raise ValueError('missing handoff producer allowlist')
    producer_versions = re.findall(r'\d+\.\d+\.\d+', match[1])
    for current in (old_prof, profiler_version):
        if current not in producer_versions:
            producer_versions.append(current)
    allow = ', '.join(producer_versions[:-1]) + ' and ' + producer_versions[-1]
    texts[handoff] = texts[handoff][:match.start(1)] + allow + texts[handoff][match.end(1):]
    fixtures = repo / 'tools/fixtures/perf_reports'
    saved_fixtures = {p: p.read_bytes() for p in fixtures.glob('*.json')}
    if dry_run:
        for p in files:
            print(f'Would update {p.relative_to(repo)}')
        print(f'Would regenerate 21 fixtures; core {core_version}, profiler {profiler_version}')
        return
    try:
        for p, text in texts.items():
            p.write_bytes(text.encode('utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-B', '-I', str(repo / 'tools/make_perf_fixtures.py'), directory],
                           cwd=repo, check=True, capture_output=True)
            generated = list(Path(directory).glob('*.json'))
            if len(generated) != 21:
                raise ValueError('expected 21 generated performance fixtures')
            for p in generated:
                (fixtures / p.name).write_bytes(p.read_bytes())
    except BaseException:
        for p, data in {**original, **saved_fixtures}.items():
            p.write_bytes(data)
        raise
    print(f'Core {core_version}; profiler {profiler_version}; regenerated 21 fixtures')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', type=version)
    parser.add_argument('--profiler-version', required=True, type=version)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        bump(args.repo, args.version, args.profiler_version, args.dry_run)
    except (OSError, ValueError, subprocess.CalledProcessError, StopIteration) as error:
        parser.exit(1, f'bump failed: {error}\n')


if __name__ == '__main__':
    main()
