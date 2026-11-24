#!/usr/bin/env python3
"""Collects the raw material of a PR mind map with the gh CLI.

Usage: python3 extract.py <PR or stack URL> [...] [--no-chain] [--out raw.json]

For each PR: number, URL, title, body, base and head branches, state, commits and changed files; for each file,
the functions, classes, methods and React components that its diff defines (`added`), which of them are exported
(`exported`), the existing ones whose body it changes (`touched`), the types and interfaces it declares (`types`),
the definitions it deletes (`removed`) and the added ones that come from another file of the PR or from the old
path of a renamed file (`moved`, with `same: true` when the body is the same line by line). Of the added ones,
`guards` are type guards (a `x is T` return type or an `is…`/`has…` name) and `small` have a body of three lines at
most. A file renamed without changes shows no names. Test, snapshot and asset files are skipped.

A stack link (github.com/o/r/stack/1491) brings the PRs of that GitHub stack, bottom to top. Without --no-chain,
a PR link brings its whole chain: the PRs below it (whose head is its base, down to the default branch) and the open
PRs above it (whose base is its head), in merge order. `stack` of a PR is the number of its GitHub stack or null.

raw.json: {repo, default, prs: [{n, url, title, body, base, head, stack, state, draft, commits, additions, deletions,
           files: [{path, additions, deletions, added, exported, touched, types, removed, guards, small,
                    moved: [{name, from, same}]}]}]}
"""
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

URL = re.compile(r'github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)')
STACK_URL = re.compile(r'github\.com/([^/\s]+/[^/\s]+)/stacks?/(\d+)')
FIELDS = 'number,url,title,body,baseRefName,headRefName,state,isDraft,commits,files,additions,deletions'
SKIPPED = re.compile(
    r'(\.test\.|\.spec\.|_test\.|/tests?/|/__tests__/|__snapshots__|\.stories\.|/fixtures?/|'
    r'\.(snap|webp|png|jpe?g|gif|svg|ico|json|lock|md|mdx|scss|css|less|ya?ml|toml|txt|map)$)')
# Each pattern captures the name of a definition at the start of a line of code.
DEFINITIONS = [
    re.compile(r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)'),
    re.compile(r'^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)'),
    re.compile(r'^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^>]*>\s*)?\([^)]*\)?\s*(?::[^=]+)?=>'),
    re.compile(r'^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^>]*>\s*)?\(?[\w$]*\)?\s*=>'),
    re.compile(r'^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*$'),
    re.compile(r'^\s+(?:(?:private|public|protected|static|readonly|async|override)\s+)*([a-z_$][\w$]*)\s*'
               r'(?:=\s*(?:async\s*)?\([^)]*\)\s*=>|\([^)]*\)\s*(?::\s*[^{]+)?\{)\s*$'),
    re.compile(r'^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)'),
    re.compile(r'^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)'),
    re.compile(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)'),
]
TYPE = re.compile(r'^(?:export\s+)?(?:declare\s+)?(?:type|interface|enum)\s+([A-Za-z_$][\w$]*)')
NOT_NAMES = {'if', 'for', 'while', 'switch', 'return', 'catch', 'constructor', 'function', 'super', 'render'}
HUNK = re.compile(r'^@@ [^@]+ @@ ?(.*)$')


def gh(*args):
    try:
        res = subprocess.run(['gh', *args], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('The gh CLI is not installed: https://cli.github.com')
    if res.returncode:
        sys.exit(f'gh {" ".join(args)}: {res.stderr.strip() or "failed"}')
    return res.stdout


def stack_of(repo, n):
    """The number of the GitHub stack of PR `n`, or None: a host without stacks answers with an error."""
    res = subprocess.run(['gh', 'api', f'repos/{repo}/pulls/{n}', '--jq', '.stack.number // empty'],
                         capture_output=True, text=True)
    return int(res.stdout) if res.returncode == 0 and res.stdout.strip().isdigit() else None


def definition(code):
    """The name that a line of code defines, or None."""
    for pattern in DEFINITIONS:
        m = pattern.match(code)
        if m:
            return None if m.group(1) in NOT_NAMES else m.group(1)
    return None


EMPTY = {'added': [], 'exported': [], 'touched': [], 'types': [], 'removed': [], 'guards': [], 'small': [], 'moved': []}
GUARD = re.compile(r'\)\s*:\s*(?:asserts\s+)?[\w$.]+\s+is\s|->\s*Type(?:Guard|Is)\[')
GUARD_NAME = re.compile(r'^(?:is|has)[A-Z_]')
EXPORT = re.compile(r'^export\s+(?:default\s+)?')
CLOSING = re.compile(r'^\s*[}\])]')


def body_of(lines, start, sign):
    """The lines of the definition at `lines[start]`, while they carry `sign`: stripped, blank ones dropped."""
    first = lines[start][1:]
    indent = len(first) - len(first.lstrip())
    body = [EXPORT.sub('', first.strip())]
    for line in lines[start + 1:]:
        if not line.startswith(sign):
            break
        code = line[1:]
        if not code.strip():
            continue
        if len(code) - len(code.lstrip()) <= indent:
            if CLOSING.match(code):
                body.append(code.strip())
            break
        body.append(code.strip())
    return '\n'.join(body)


def names(diff):
    """Per changed source file: the names its diff defines, changes and deletes, and the ones moved in from another file."""
    lines = diff.splitlines()
    files, current, old, plus, minus, renamed, header = {}, None, None, {}, {}, {}, True
    for i, line in enumerate(lines):
        if line.startswith('diff --git '):
            current, old, header = None, None, True
        elif header and line.startswith('--- '):
            old = line[6:] if line.startswith('--- a/') else None
        elif header and line.startswith('+++ '):
            # A deleted file has no new path: its definitions belong to the old one.
            path = line[6:] if line.startswith('+++ b/') else old
            current = None if not path or SKIPPED.search(path) else files.setdefault(path, {key: [] for key in EMPTY})
            if current is not None:
                plus.setdefault(path, {})
                minus.setdefault(path, {})
                if old and old != path:
                    renamed[path] = old
        elif line.startswith('@@'):
            header = False
            # The hunk header carries the line of the definition that the hunk is inside of.
            m = HUNK.match(line)
            name = m and current is not None and definition(m.group(1))
            if name and name not in current['touched']:
                current['touched'].append(name)
        elif current is not None and line.startswith(('+', '-')):
            sign, code = line[0], line[1:]
            declared = TYPE.match(code)
            if declared:
                if sign == '+' and declared.group(1) not in current['types']:
                    current['types'].append(declared.group(1))
                continue
            name = definition(code)
            if not name:
                continue
            if sign == '-':
                if name not in current['removed']:
                    current['removed'].append(name)
                    minus[path][name] = body_of(lines, i, '-')
            elif name not in current['added']:
                current['added'].append(name)
                plus[path][name] = body_of(lines, i, '+')
                if code.startswith('export'):
                    current['exported'].append(name)
                if GUARD.search(code) or GUARD_NAME.match(name):
                    current['guards'].append(name)
                elif plus[path][name].count('\n') < 3:
                    current['small'].append(name)
    for path, found in files.items():
        added = found['added']
        # The same body deleted and added in one file is a reordering, not a new definition.
        found['added'] = [name for name in added if minus[path].get(name) != plus[path][name]]
        for key in ('exported', 'guards', 'small'):
            found[key] = [name for name in found[key] if name in found['added']]
        found['removed'] = [name for name in found['removed'] if name not in added]
        found['touched'] = [name for name in found['touched'] if name not in added and name not in found['removed']]
        # A renamed file shows a definition as deleted and added only when its body changed on the way.
        found['moved'] = [{'name': name, 'from': renamed[path], 'same': False}
                          for name in found['added'] if path in renamed and name in minus[path]]
    for path, found in files.items():
        for name in found['added']:
            source = next((other for other in files if other != path and name in files[other]['removed']), None)
            if source and all(m['name'] != name for m in found['moved']):
                found['moved'].append({'name': name, 'from': source, 'same': minus[source][name] == plus[path][name]})
    return files


def chain(repo, start, default, view):
    """`start` with the PRs below it down to the default branch and the open PRs stacked above it."""
    open_prs = json.loads(gh('pr', 'list', '-R', repo, '--state', 'open', '--limit', '1000',
                             '--json', 'number,baseRefName,headRefName'))
    by_head = {pr['headRefName']: pr for pr in open_prs}
    seen, below, pr = {start}, [], view(start)
    while pr['baseRefName'] != default:
        parent = by_head.get(pr['baseRefName'])
        if parent is None:
            # The PR below may be merged or closed already.
            found = json.loads(gh('pr', 'list', '-R', repo, '--head', pr['baseRefName'], '--state', 'all',
                                  '--json', 'number,baseRefName,headRefName', '--limit', '5'))
            parent = found[0] if found else None
        if parent is None or parent['number'] in seen:
            break
        seen.add(parent['number'])
        below.insert(0, parent['number'])
        pr = parent
    above, queue = [], [view(start)['headRefName']]
    while queue:
        head = queue.pop(0)
        for pr in sorted((p for p in open_prs if p['baseRefName'] == head), key=lambda p: p['number']):
            if pr['number'] not in seen:
                seen.add(pr['number'])
                above.append(pr['number'])
                queue.append(pr['headRefName'])
    return below + [start] + above


def collect(urls, with_chain=True, log=lambda message: print(message, file=sys.stderr)):
    targets = []
    for url in urls:
        m = URL.search(url) or STACK_URL.search(url)
        if not m:
            sys.exit(f'not a GitHub PR or stack link: {url}')
        targets.append((m.group(1), int(m.group(2)), m.re is STACK_URL))
    repos = {repo for repo, _, _ in targets}
    if len(repos) != 1:
        sys.exit(f'all PRs must be in one repository, got {sorted(repos)}')
    repo = repos.pop()
    default = json.loads(gh('repo', 'view', repo, '--json', 'defaultBranchRef'))['defaultBranchRef']['name']
    views = {}

    def view(n):
        if n not in views:
            views[n] = json.loads(gh('pr', 'view', str(n), '-R', repo, '--json', FIELDS))
        return views[n]

    def members(n, is_stack):
        if is_stack:
            return [int(m) for m in gh('api', f'repos/{repo}/stacks/{n}', '--jq', '.pull_requests[].number').split()]
        return chain(repo, n, default, view) if with_chain else [n]

    order = []
    for _, n, is_stack in targets:
        for m in members(n, is_stack):
            if m not in order:
                order.append(m)
    # Every PR needs its metadata, its diff and its stack: independent requests, so they run side by side.
    with ThreadPoolExecutor(max_workers=8) as pool:
        metas = list(pool.map(view, order))
        diffs = list(pool.map(lambda n: gh('pr', 'diff', str(n), '-R', repo, '--color=never'), order))
        stacks = list(pool.map(lambda n: stack_of(repo, n), order))
    prs = []
    for pr, diff, stack in zip(metas, diffs, stacks):
        found = names(diff)
        files = [{'path': f['path'], 'additions': f['additions'], 'deletions': f['deletions'],
                  **found.get(f['path'], EMPTY)} for f in pr['files']]
        prs.append({
            'n': pr['number'], 'url': pr['url'], 'title': pr['title'], 'body': (pr['body'] or '')[:3000],
            'base': pr['baseRefName'], 'head': pr['headRefName'], 'stack': stack,
            'state': pr['state'], 'draft': pr['isDraft'],
            'commits': [c['messageHeadline'] for c in pr['commits']],
            'additions': pr['additions'], 'deletions': pr['deletions'], 'files': files,
        })
        log(f'#{pr["number"]} {pr["title"]}: {sum(len(f["added"]) for f in files)} names')
    return {'repo': repo, 'default': default, 'prs': prs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('urls', nargs='+')
    ap.add_argument('--no-chain', action='store_true')
    ap.add_argument('--out', default='raw.json')
    args = ap.parse_args(argv)
    raw = collect(args.urls, with_chain=not args.no_chain)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=1)
    print(f'ok: {len(raw["prs"])} PRs → {args.out}')


if __name__ == '__main__':
    main()
