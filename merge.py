#!/usr/bin/env python3
"""Folds the analysis of each PR into data.json: `about`, `without` and `risks` from analysis/<n>.json.

Usage: python3 merge.py data.json [--dir DIR]

DIR (default: the folder `analysis` next to data.json) holds one file per PR, written by the agent that follows
analysis.md:
{"pr": 1475, "fns": {"SettingsDialog": {"about": "...", "without": "...", "risks": [
  {"title": "...", "what": "...", "why": "...", "suggestion": "...", "level": "mid", "at": "src/a.ts:40"}]}}}
A function of the PR takes these three fields. Other fields, other names and PRs without a file are listed; data.json
gets the rest, and the exit code is 1 while the list is not empty. The builder checks the values.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build import functions, unchanged_move  # noqa: E402

FIELDS = ('about', 'without', 'risks')


def merge(data, analyses):
    """Sets the fields of `analyses` ({PR number: {"fns": {name: fields}}}) on the functions of the data; returns
    what was left out. A PR split into several cards of the map is one PR here."""
    by_pr = {}
    for st in data['stacks']:
        for pr in st['prs']:
            by_pr.setdefault(pr['n'], {}).update({f['name']: f for g in pr['groups'] for f in g['fns']})
    problems = [f'#{n}: no analysis' for n in by_pr if n not in analyses]
    for n, found in analyses.items():
        fns = by_pr.get(n)
        if fns is None:
            problems.append(f'#{n}: not a PR of the map')
            continue
        done = found.get('fns', {})
        for name, fields in done.items():
            f = fns.get(name)
            if f is None or unchanged_move(f):
                problems.append(f'#{n}: {name} is not a function of the PR to analyse')
                continue
            extra = sorted(set(fields) - set(FIELDS))
            if extra:
                problems.append(f'#{n}: {name}: {", ".join(extra)} left out')
            f.update({key: value for key, value in fields.items() if key in FIELDS})
        missing = [name for name, f in fns.items() if not unchanged_move(f) and name not in done]
        if missing:
            problems.append(f'#{n}: no analysis of {", ".join(missing)}')
    return problems


def read(folder):
    """{PR number: analysis} from the JSON files of `folder`, and the files that could not be read."""
    analyses, problems = {}, []
    for path in sorted(Path(folder).glob('*.json')):
        try:
            found = json.loads(path.read_text(encoding='utf-8'))
            analyses[int(found.get('pr', path.stem))] = found
        except (ValueError, TypeError, AttributeError) as error:
            problems.append(f'{path.name}: {error}')
    return analyses, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('data')
    ap.add_argument('--dir', help='the folder of analysis/<n>.json (default: analysis next to the data)')
    args = ap.parse_args(argv)
    path = Path(args.data)
    data = json.loads(path.read_text(encoding='utf-8'))
    analyses, problems = read(args.dir or path.with_name('analysis'))
    problems += merge(data, analyses)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for line in problems:
        print(f'left out: {line}', file=sys.stderr)
    done = sum(1 for f in functions(data) if isinstance(f.get('risks'), list))
    print(f'ok: analysis of {len(analyses)} PRs, {done}/{len(functions(data))} functions with risks → {path}')
    if problems:
        sys.exit(1)


if __name__ == '__main__':
    main()
