#!/usr/bin/env python3
"""Finds where each function of a map is declared and used: `file`, `line`, `code` and `uses` of data.json.

Usage: python3 uses.py data.json [--cache DIR]

The heads of the map's PRs and the default branch come into a bare cache repository with one shallow fetch through
the gh credentials. The declaration is looked up at the head of the function's own PR, in the files that the PR
changes first; a function that the default branch declares already gets `code`, the link to that declaration.
The uses are looked up at the top of the function's stack: the last PR whose chain of bases leads down to its PR, so
the calls added by the PRs above count too. A function moved without changes gets no uses.

A use is a line of product code that names the function; tests, stories, fixtures, comments, imports, re-exports,
closing JSX tags and declarations do not count. The lines inside one function make one place:
{"in": name, "pr": n or null, "url": link to the line}. `in` is the function around the line (`Owner.method` for a
method, the name of the map function when the map has it, the file name at the top level); `pr` is the PR of the
chain that added the line, null when the default branch has it already. A suffix in parentheses
(`Header (options)`) is not a part of a name; `Owner.member` looks for `.member` in the files that name `Owner`.
"""
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build import PR_URL, functions  # noqa: E402
from extract import TYPE, definition, gh  # noqa: E402

CACHE = Path.home() / '.cache' / 'pr-mindmap'
CODE = ['*.ts', '*.tsx', '*.mts', '*.cts', '*.js', '*.jsx', '*.mjs', '*.cjs', '*.vue', '*.svelte',
        '*.py', '*.go', '*.rs', '*.java', '*.kt', '*.swift', '*.rb', '*.php', '*.cs']
NOT_PRODUCT = re.compile(r'(\.test\.|\.spec\.|_test\.|/tests?/|/__tests__/|/e2e/|/playwright/|\.stories\.|'
                         r'/stories/|/demo/|/fixtures?/|/__mocks__/|/mocks?/)')
IMPORTS = re.compile(
    r'''^[ \t]*(?:import[ \t]*['"][^'"\n]*['"]'''
    r'''|import\b[^;]*?\bfrom[ \t]*['"][^'"\n]*['"]'''
    r'''|export[ \t]+(?:type[ \t]+)?(?:\*(?:[ \t]+as[ \t]+[\w$]+)?|\{[^}]*\})(?:[ \t]*from[ \t]*['"][^'"\n]*['"])?'''
    r'''|export[ \t]+default[ \t]+[\w$.]+;?[ \t]*$'''
    r'''|from[ \t]+[\w.]+[ \t]+import[ \t]+(?:\([^)]*\)|[^\n]*)'''
    r'''|import[ \t]+[\w., \t]+$)''', re.M)
COMMENT = re.compile(r'^\s*(?://|/\*|\*|#)')
# The closing tag of a JSX element belongs to the use that its opening tag starts.
CLOSING_TAG = re.compile(r'</[\w$.:-]+\s*>')
# A line that closes a bracket continues a construct above it: `}: Props) {`, `} else {`.
CLOSING = re.compile(r'^\s*[}\])]')
CLASS = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)')
OBJECT = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*\{\s*$')
# A constant that holds a function whose parameters or body go on below: `const Banner: FC<Props> = ({`.
FUNCTION_CONST = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*'
                            r'(?:async\s*)?(?:\(|function\b|<|[\w$]+\s*=>)')
# A member of an object literal that holds a function: `create: (schema) =>`, `render: function`.
PROPERTY = re.compile(r'^\s+([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?(?:\([^)]*\)\s*(?::[^=]+)?=>|function\b|[\w$]+\s*=>)')


def bare(name):
    """`Header (options)` → `Header`."""
    return re.sub(r'\s*\(.*\)$', '', name).strip()


def word(name):
    return re.compile(rf'(?<![\w$]){re.escape(name)}(?![\w$])')


def indent(line):
    return len(line) - len(line.lstrip())


def git(cache, *args, data=None):
    res = subprocess.run(['git', '--git-dir', str(cache), *args], input=data, capture_output=True)
    # git grep answers 1 when nothing matches.
    if res.returncode and not (args[0] == 'grep' and res.returncode == 1):
        sys.exit(f'git {" ".join(args[:3])}: {res.stderr.decode(errors="replace").strip() or "failed"}')
    return res.stdout


def fetch(repo, refs, cache):
    """`refs` maps a local name to a ref of `repo`; each comes as refs/prmap/<name> of the cache repository."""
    if not (cache / 'HEAD').exists():
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '--bare', '-q', str(cache)], check=True)
    git(cache, '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
        'fetch', '-q', '--depth', '1', '--no-tags', f'https://github.com/{repo}.git',
        *(f'+{remote}:refs/prmap/{name}' for name, remote in refs.items()))


class Tree:
    """The product code of one ref of the cache repository, read on demand."""

    def __init__(self, cache, ref):
        self.cache, self.ref, self.files, self.texts = cache, ref, {}, {}
        self.sha = git(cache, 'rev-parse', ref).decode().strip()

    def grep(self, words):
        """The product code files that contain one of `words`."""
        pattern = [arg for w in sorted(words) for arg in ('-e', w)]
        listed = git(self.cache, 'grep', '-l', '-w', '-F', *pattern, self.ref, '--', *CODE).decode().splitlines()
        paths = [line.split(':', 1)[1] for line in listed]
        return [p for p in paths if not NOT_PRODUCT.search('/' + p)]

    def lines(self, path):
        """The lines of `path`, or None when the ref has no such file."""
        self.read([path])
        return self.files[path]

    def has(self, path, text):
        """Whether a line of `path` reads `text`, spaces around aside."""
        if path not in self.texts:
            self.texts[path] = {line.strip() for line in self.lines(path) or []}
        return text in self.texts[path]

    def read(self, paths):
        paths = [p for p in dict.fromkeys(paths) if p not in self.files]
        if not paths:
            return
        out = git(self.cache, 'cat-file', '--batch', data=''.join(f'{self.ref}:{p}\n' for p in paths).encode())
        at = 0
        for path in paths:
            end = out.index(b'\n', at)
            head = out[at:end].split()
            if head[-1] == b'missing':
                self.files[path], at = None, end + 1
                continue
            size = int(head[2])
            self.files[path] = out[end + 1:end + 1 + size].decode(errors='replace').splitlines()
            at = end + 2 + size


def skipped(lines):
    """The numbers of the lines that hold imports, re-exports or comments."""
    text = '\n'.join(lines)
    out = {i for i, line in enumerate(lines) if COMMENT.match(line)}
    for m in IMPORTS.finditer(text):
        out.update(range(text.count('\n', 0, m.start()), text.count('\n', 0, m.end()) + 1))
    return out


def declared(line):
    """The name of the function that a line of code declares, or None."""
    m = FUNCTION_CONST.match(line) or PROPERTY.match(line)
    return definition(line) or (m.group(1) if m else None)


def around(lines, i):
    """The function that line `i` is inside of, or declares in one line: `Owner.method` for a method, the outermost
    function else."""
    limit, name = indent(lines[i]), declared(lines[i])
    for line in reversed(lines[:i]):
        if not line.strip() or indent(line) >= limit or CLOSING.match(line):
            continue
        limit = indent(line)
        owner = CLASS.match(line) or OBJECT.match(line)
        if owner and name:
            return f'{owner.group(1)}.{name}'
        # A local function is a part of the function around it.
        name = (None if owner else declared(line)) or name
        if limit == 0:
            break
    return name


def declares(line, member):
    typed = TYPE.match(line)
    return declared(line) == member or bool(typed and typed.group(1) == member)


def declaration(tree, name, prefer=()):
    """`file` and `line` of the declaration of `name` in `tree`, looking at the files of `prefer` first."""
    owner, _, member = bare(name).rpartition('.')
    paths = tree.grep({member})
    tree.read(paths)
    rank = {p: i for i, p in enumerate(prefer)}
    for path in sorted(paths, key=lambda p: (rank.get(p, len(rank)), p)):
        lines = tree.lines(path) or []
        if owner and not any(word(owner).search(line) for line in lines):
            continue
        for i, line in enumerate(lines):
            if declares(line, member):
                return {'file': path, 'line': i + 1}
    return {}


def places(tree, name, aliases, only=None):
    """{(path, the function around the uses): the line of the first use} of `name` in `tree`; a method without its
    owner in the name is looked for in its own file `only`."""
    owner, _, member = bare(name).rpartition('.')
    if owner:
        target = re.compile(rf'\.{re.escape(member)}(?![\w$])')
    else:
        # `list.includes(x)` calls a method of `list`, not the function `includes`.
        target = word(member) if only else re.compile(rf'(?<![\w$.]){re.escape(member)}(?![\w$])')
    paths = [only] if only else tree.grep({owner or member, member})
    tree.read(paths)
    found = {}
    for path in paths:
        lines = tree.lines(path) or []
        if owner and not any(word(owner).search(line) for line in lines):
            continue
        skip = skipped(lines)
        for i, line in enumerate(lines):
            if i in skip or declares(line, member) or not target.search(CLOSING_TAG.sub('', line)):
                continue
            where = around(lines, i) or PurePosixPath(path).name
            if bare(where) not in (bare(name), member):
                found.setdefault((path, aliases.get(where, where)), i + 1)
    return found


def chains(prs):
    """Per PR: its chain by the bases of the PRs, from the lowest PR below it to the top of its stack."""
    by_head = {pr['head']: n for n, pr in prs.items()}
    out = {}
    for n in prs:
        chain, at = [n], n
        while by_head.get(prs[at]['base']) not in (None, *chain):
            at = by_head[prs[at]['base']]
            chain.insert(0, at)
        at = n
        while True:
            up = [m for m, pr in prs.items() if pr['base'] == prs[at]['head'] and m not in chain]
            if not up:
                break
            at = up[-1]
            chain.append(at)
        out[n] = chain
    return out


def unchanged_move(f):
    return bool(f.get('moved')) and not f['moved'].get('changed')


def count_all(data, cache=CACHE, log=lambda message: print(message, file=sys.stderr)):
    """Sets `file`, `line`, `code` and `uses` of the functions and `default` of the map; returns the number of PRs."""
    by_pr, repo = {}, None
    for st in data['stacks']:
        for pr in st['prs']:
            m = PR_URL.match(pr['url'])
            if not m:
                sys.exit(f'#{pr["n"]}: {pr["url"]} is not a GitHub PR link')
            repo = m.group(1).removeprefix('https://github.com/')
            by_pr.setdefault(pr['n'], []).extend(f for g in pr['groups'] for f in g['fns'])
    default = json.loads(gh('repo', 'view', repo, '--json', 'defaultBranchRef'))['defaultBranchRef']['name']
    with ThreadPoolExecutor(max_workers=8) as pool:
        views = list(pool.map(lambda n: json.loads(gh('pr', 'view', str(n), '-R', repo, '--json',
                                                      'baseRefName,headRefName,files')), by_pr))
    prs = {n: {'base': v['baseRefName'], 'head': v['headRefName'], 'files': [f['path'] for f in v['files']]}
           for n, v in zip(by_pr, views)}
    cache = Path(cache) / repo.replace('/', '__')
    fetch(repo, {'main': f'refs/heads/{default}', **{str(n): f'pull/{n}/head' for n in by_pr}}, cache)
    main_tree = Tree(cache, 'refs/prmap/main')
    trees = {n: Tree(cache, f'refs/prmap/{n}') for n in by_pr}
    chain = chains(prs)
    # Code calls a map function by its bare name: `Header (options)` answers to `Header`.
    aliases = {}
    for fns in by_pr.values():
        for f in fns:
            aliases.setdefault(bare(f['name']), f['name'])
    for n, fns in by_pr.items():
        top = trees[chain[n][-1]]
        order = {m: i for i, m in enumerate(chain[n])}
        for f in fns:
            f.update(declaration(trees[n], f['name'], [f.get('file'), *prs[n]['files']]))
            f.pop('code', None)
            # The default branch declares it in the same file, or in the file it moves from.
            existing = declaration(main_tree, f['name'], [f.get('file')])
            if existing and existing['file'] in (f.get('file'), (f.get('moved') or {}).get('from')):
                f['code'] = f'https://github.com/{repo}/blob/{main_tree.sha}/{existing["file"]}#L{existing["line"]}'
            if unchanged_move(f):
                f.pop('uses', None)
                continue
            # A method named without its owner (`includes`) shares its name with methods of other objects: its own
            # file is the only one that surely calls it.
            lines = trees[n].lines(f['file']) if f.get('file') else None
            method = '.' not in bare(f['name']) and lines and indent(lines[f['line'] - 1]) > 0
            uses = []
            for (path, where), line in places(top, f['name'], aliases, f['file'] if method else None).items():
                text = top.lines(path)[line - 1].strip()
                added = None if main_tree.has(path, text) else next((m for m in chain[n] if trees[m].has(path, text)), None)
                uses.append({'in': where, 'pr': added, 'url': f'https://github.com/{repo}/blob/{top.sha}/{path}#L{line}'})
            f['uses'] = sorted(uses, key=lambda u: (u['pr'] is None, order.get(u['pr'], 0), u['in']))
        log(f'#{n}: {len(fns)} functions, uses at the head of #{chain[n][-1]}')
    data['default'] = default
    return len(by_pr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('data')
    ap.add_argument('--cache', default=str(CACHE), help=f'folder of the cache repositories (default: {CACHE})')
    args = ap.parse_args(argv)
    path = Path(args.data)
    data = json.loads(path.read_text(encoding='utf-8'))
    prs = count_all(data, args.cache)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'ok: declarations and uses of {len(functions(data))} functions in {prs} PRs → {path}')


if __name__ == '__main__':
    main()
