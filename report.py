#!/usr/bin/env python3
"""Prepares the report of the risks of a map for the review-findings-report skill: findings.json and context.md.

Usage: python3 report.py data.json [--dir DIR] [--cache DIR]

DIR (default: the folder `report` next to data.json) gets findings.json, one finding per risk in the order of the
map, and context.md, where the code of each PR is read. Each risk of data.json gets `id`, the number of its card, and
data.json gets `report`, the path of DIR/index.html from its folder: map.html links each risk to its card there.
The skill writes DIR/f<id>.json and DIR/index.html.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build import AT, PR_URL, at_link, check, diff_link, risks  # noqa: E402
from uses import CACHE  # noqa: E402

TITLE = {'en': '{}: risks of the functions', 'ru': '{}: риски функций'}


def repo_of(data):
    return PR_URL.match(data['stacks'][0]['prs'][0]['url']).group(1).removeprefix('https://github.com/')


def findings(data):
    """Numbers the risks of the map and returns the findings of the report."""
    out = []
    for i, (pr, f, r) in enumerate(risks(data), 1):
        r['id'] = i
        path, line = AT.match(r['at']).groups() if r.get('at') else (f.get('file', ''), f.get('line'))
        out.append({'id': i, 'pr': pr['n'], 'url': at_link(pr, r['at']) if r.get('at') else diff_link(pr, f) or pr['url'],
                    'path': path, 'line': int(line) if line else None, 'fn': f['name'], 'title': r['title'],
                    **{key: r.get(key, '') for key in ('what', 'why', 'suggestion')}})
    return out


def context(data, data_path, cache):
    repo = repo_of(data)
    git = f'git --git-dir {cache / repo.replace("/", "__")}'
    out = ['# Context of the report', '',
           f'The findings are the risks of the functions of the map `{data_path}`. The field `fn` of a finding names its '
           'function; the card of the function in the map has `why`, `about`, `without` and `uses`.', '',
           '## Code', '',
           f'- The diff of a PR: `gh pr diff <n> -R {repo}`.',
           f'- A file at the head of a PR: `{git} show refs/prmap/<n>:<path>`; the default branch is `refs/prmap/main`.',
           '- The code is read, not run: the cache repository has no working copy and no installed dependencies.', '',
           '## Stacks', '']
    for st in data['stacks']:
        numbers = list(dict.fromkeys(pr['n'] for pr in st['prs']))
        out.append(f'- {st["name"]}: ' + ' → '.join(f'#{n}' for n in numbers) + f' from the bottom; the top PR is '
                   f'#{numbers[-1]}.')
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('data')
    ap.add_argument('--dir', help='the folder of the report (default: report next to the data)')
    ap.add_argument('--cache', default=str(CACHE), help=f'folder of the cache repositories of uses.py (default: {CACHE})')
    args = ap.parse_args(argv)
    path = Path(args.data).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    errors = check(data)
    if errors:
        sys.exit('\n'.join(errors))
    folder = Path(args.dir).resolve() if args.dir else path.with_name('report')
    folder.mkdir(parents=True, exist_ok=True)
    found = findings(data)
    title = TITLE['ru' if data.get('lang') == 'ru' else 'en'].format(data['title'])
    (folder / 'findings.json').write_text(json.dumps({'title': title, 'repo': repo_of(data), 'findings': found},
                                                     ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (folder / 'context.md').write_text(context(data, path, Path(args.cache)), encoding='utf-8')
    data['report'] = os.path.relpath(folder / 'index.html', path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'ok: {len(found)} findings → {folder / "findings.json"}')


if __name__ == '__main__':
    main()
