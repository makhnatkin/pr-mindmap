#!/usr/bin/env python3
"""Builds the mind map (HTML) and the Markdown list of a PR set from data.json.

Usage: python3 build.py data.json [--html map.html] [--artifact map.artifact.html] [--md map.md]
                                  [--data-js map-data.js] [--open]

With no output option it writes map.html, map.artifact.html and map.md next to data.json (named after the data
file when it is not called data.json). With any of them it writes only the ones asked for.

--html      a complete document to open from disk;
--artifact  the same page without the document skeleton: the form the Artifact tool publishes;
--md        the map as a Markdown list;
--data-js   the data as a script: template.html opened from the same folder reads it, which shows the map
            straight from the template while the template is edited;
--open      opens the built page in the browser.

data.json:
{
  "title": "Banner stack map",               # page title, a name of 2-4 words
  "lang": "en",                               # optional, the language of the map text: "en" or "ru"
  "root": {"title": "...", "essence": "..."},  # essence <= 150 chars
  "stacks": [{
    "name": "...", "gh": "stack 1491 | no stack", "essence": "...",   # essence <= 150; "stack N" links the GitHub stack
    "prs": [{
      "n": 1475, "url": "https://github.com/o/r/pull/1475", "branch": "feat/x",
      "state": "open | draft | merged | closed",                         # optional, the icon of the PR
      "title": "...", "essence": "...",                                   # essence <= 200
      "groups": [{"name": "...", "fns": [
        {"name": "uniqueName", "why": "<= 50 chars", "key": true, "kind": "s|u", "cat": "<cat id>",
         "type": "logic | guard | util",   # real work, a type guard, or a small utility
         "about": "<= 400 chars",          # what it is for, in plain words for a reader who does not write code
         "without": "<= 200 chars",        # a sentence on whether the product can do without it, and the risk
         "ext": "YfmTabs",                 # <= 40 chars: its plugin or extension, else its package or module
         "file": "src/a.ts", "line": 12,   # the declaration at the head of the PR (uses.py)
         "code": "https://github.com/…",   # the declaration in the default branch, when the function exists there
         "uses": [{"in": "Caller", "pr": 1480, "url": "https://github.com/…"}],   # the places that use it (uses.py);
                                           # "pr": null for a place the default branch has already
         "moved": {"from": "src/b.ts", "to": "src/a.ts", "changed": true}}
                                           # optional: moved from another file; an unchanged move needs nothing else
      ]}]
    }]
  }],
  "cats": [{"id": "cmd", "name": "Commands", "desc": "Functions that ...",
            "colors": ["#cc4a12", "#ff8a4c"]}],   # 1-10 categories, optional light/dark hex colors
  "sims": [{"id": "values", "label": "...", "members": ["fnA", "fnB"]}],         # groups of very similar functions
  "default": "main"                           # optional: the default branch of the repository (uses.py)
}
Function names must be unique across the map: add a short suffix in parentheses when two PRs touch the same name.
The fields after `cat` are optional for the builder; the `ok` line counts the functions that have them.
A category id becomes a part of a CSS name: lowercase Latin letters, digits and hyphens, starting with a letter.
"""
import argparse
import hashlib
import html
import json
import re
import sys
import webbrowser
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIMITS = {'root': 150, 'stack': 150, 'pr': 200, 'why': 50, 'about': 500, 'without': 200, 'ext': 40}
TYPES = ('logic', 'guard', 'util')
PR_STATES = ('open', 'draft', 'merged', 'closed')
CAT_ID = re.compile(r'^[a-z][a-z0-9-]*$')
CAT_COLOR = re.compile(r'#[0-9a-fA-F]{6}')
STACK_GH = re.compile(r'\bstack\s+#?(\d+)', re.I)
PR_URL = re.compile(r'^(https://github\.com/[^/]+/[^/]+)/pull/\d+')
# Default light and dark category colors for maps without explicit colors.
PALETTE = [
    ('#6d4fe0', '#ab98ff'), ('#0b8276', '#3ccfbf'), ('#2563d9', '#7aa7ff'), ('#cc4a12', '#ff8a4c'),
    ('#9a6b00', '#f2c14e'), ('#c2255c', '#ff6b9a'), ('#4f8a10', '#94d82d'), ('#0d8aa0', '#4dd4ea'),
    ('#9c36b5', '#e07cf0'), ('#8a6152', '#d1a894'),
]
DATA_TAG = '<script src="map-data.js"></script>'
STANDALONE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>:root{{color-scheme:light}}body{{margin:0}}[hidden]{{display:none!important}}</style>
{head}
</head>
<body>
{body}
</body>
</html>
"""


def functions(data):
    return [f for st in data['stacks'] for pr in st['prs'] for g in pr['groups'] for f in g['fns']]


def unchanged_move(f):
    return isinstance(f.get('moved'), dict) and not f['moved'].get('changed')


def described(f):
    """An unchanged move, or a function with its type, plugin, places of use, explanation and risk."""
    return unchanged_move(f) or (all(f.get(field) for field in ('type', 'ext', 'about', 'without')) and 'uses' in f)


def is_count(value, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def detail_problems(f):
    why = f.get('why', '')
    if not why and not unchanged_move(f):
        yield 'why is empty'
    elif len(why) > LIMITS['why']:
        yield f'why {len(why)} > {LIMITS["why"]} «{why}»'
    for field in ('about', 'without', 'ext'):
        if field not in f:
            continue
        if not is_text(f[field]):
            yield f'{field} is empty'
        elif len(f[field]) > LIMITS[field]:
            yield f'{field} {len(f[field])} > {LIMITS[field]}'
    if f.get('type', 'logic') not in TYPES:
        yield f'type {f["type"]!r}, expected one of {TYPES}'
    if 'file' in f and not is_text(f['file']):
        yield 'file is empty'
    if 'line' in f and not is_count(f['line'], 1):
        yield f'line {f["line"]!r}, expected a whole number from 1'
    if 'code' in f and not str(f['code']).startswith('http'):
        yield f'code {f["code"]!r} is not a link'
    uses = f.get('uses', [])
    if not (is_count(uses) or isinstance(uses, list) and all(
            isinstance(u, dict) and is_text(u.get('in')) and (u.get('pr') is None or is_count(u['pr'], 1))
            and str(u.get('url', '')).startswith('http') for u in uses)):
        yield 'uses: expected a list of {"in": name, "pr": number or null, "url": link}'
    if 'moved' in f and not (isinstance(f['moved'], dict) and isinstance(f['moved'].get('changed', False), bool)
                             and is_text(f['moved'].get('from')) and is_text(f['moved'].get('to'))):
        yield f'moved {f["moved"]!r}, expected {{"from": path, "to": path, "changed": true | false}}'


def check(data):
    """The list of what is wrong with the data; empty when the map can be built."""
    try:
        return _check(data)
    except (KeyError, TypeError) as error:
        # A missing field: the errors above it in the file are already reported by the next run.
        return [f'missing or malformed field: {error!r} (see the schema in the docstring of build.py)']


def _check(data):
    errors = []
    if not data['title'].strip():
        errors.append('title is empty')
    ids = [c['id'] for c in data['cats']]
    cats = set(ids)
    if not 1 <= len(ids) <= len(PALETTE):
        errors.append(f'cats: {len(ids)}, expected 1-{len(PALETTE)}')
    errors += [f'cat id {i!r}: lowercase Latin letters, digits and hyphens, starting with a letter' for i in ids if not CAT_ID.match(i)]
    errors += [f'duplicate cat id {i!r}' for i, n in Counter(ids).items() if n > 1]
    for cat in data['cats']:
        if 'colors' in cat:
            colors = cat['colors']
            if not (isinstance(colors, list) and len(colors) == 2
                    and all(isinstance(color, str) and CAT_COLOR.fullmatch(color) for color in colors)):
                errors.append(f"cat {cat['id']!r}: colors must contain two #RRGGBB values, light then dark")
    if len(data['root']['essence']) > LIMITS['root']:
        errors.append(f'root essence: {len(data["root"]["essence"])} > {LIMITS["root"]}')
    if not data['stacks']:
        errors.append('no stacks')
    for st in data['stacks']:
        if len(st['essence']) > LIMITS['stack']:
            errors.append(f'stack {st["name"]}: essence {len(st["essence"])} > {LIMITS["stack"]}')
        if not st['prs']:
            errors.append(f'stack {st["name"]}: no PRs')
        for pr in st['prs']:
            if len(pr['essence']) > LIMITS['pr']:
                errors.append(f'#{pr["n"]}: essence {len(pr["essence"])} > {LIMITS["pr"]}')
            if pr.get('state', 'open') not in PR_STATES:
                errors.append(f'#{pr["n"]}: state {pr["state"]!r}, expected one of {PR_STATES}')
            if not str(pr['url']).startswith('http'):
                errors.append(f'#{pr["n"]}: url {pr["url"]!r} is not a link')
            if not pr['groups']:
                errors.append(f'#{pr["n"]}: no groups')
            for g in pr['groups']:
                if not g['fns']:
                    errors.append(f'#{pr["n"]}: group {g["name"]!r} is empty')
                for f in g['fns']:
                    if f['kind'] not in ('s', 'u'):
                        errors.append(f'{f["name"]}: kind {f["kind"]!r}, expected "s" or "u"')
                    if f['cat'] not in cats:
                        errors.append(f'{f["name"]}: unknown cat {f["cat"]!r}')
                    if not isinstance(f['key'], bool):
                        errors.append(f'{f["name"]}: key {f["key"]!r}, expected true or false')
                    errors += [f'{f["name"]}: {problem}' for problem in detail_problems(f)]
    names = Counter(f['name'] for f in functions(data))
    dup = sorted(name for name, n in names.items() if n > 1)
    if dup:
        errors.append(f'duplicate function names: {dup}')
    sim_ids = Counter(s['id'] for s in data.get('sims', []))
    errors += [f'duplicate sim id {i!r}' for i, n in sim_ids.items() if n > 1]
    for s in data.get('sims', []):
        unknown = [m for m in s['members'] if m not in names]
        if unknown:
            errors.append(f'sim {s["id"]}: unknown {unknown}')
        if len(s['members']) < 2:
            errors.append(f'sim {s["id"]}: fewer than 2 members')
    return errors


def warnings(data):
    """What does not stop the build but is probably a mistake."""
    used = {f['cat'] for f in functions(data)}
    return [f'cat {c["id"]!r} has no functions' for c in data['cats'] if c['id'] not in used]


def ref_of(st):
    """The GitHub page of a stack card: the stack that `gh` names, else the only PR of the card, else None."""
    first = st['prs'][0]
    m, repo = STACK_GH.search(st['gh']), PR_URL.match(first['url'])
    if m and repo:
        return {'kind': 'stack', 'n': int(m.group(1)), 'url': f'{repo.group(1)}/stack/{m.group(1)}'}
    if len({pr['n'] for pr in st['prs']}) == 1:
        return {'kind': 'pr', 'n': first['n'], 'url': first['url']}
    return None


def diff_link(pr, f):
    """The declaration of `f` in the diff of `pr`: GitHub names a file of the diff by the SHA-256 of its path."""
    if not f.get('file'):
        return None
    line = f'R{f["line"]}' if f.get('line') else ''
    return f'{pr["url"]}/files#diff-{hashlib.sha256(f["file"].encode()).hexdigest()}{line}'


def with_sims(data):
    """A copy of the data in which each function names its similarity groups and its place in the diff of its PR,
    and each stack its GitHub page."""
    of = {}
    for s in data.get('sims', []):
        for member in s['members']:
            of.setdefault(member, []).append(s['id'])
    return {**data, 'sims': data.get('sims', []), 'stacks': [{**st, 'ref': ref_of(st), 'prs': [{**pr, 'groups': [
        {**g, 'fns': [{**f, 'sims': of.get(f['name'], []), 'diff': diff_link(pr, f)} for f in g['fns']]}
        for g in pr['groups']]} for pr in st['prs']]} for st in data['stacks']]}


MD_LABELS = {
    'en': {'essence': 'Essence', 'stack': 'Stack essence', 'pr': 'PR essence', 'key': 'Key', 'split': 'Standard / unique',
           'legend': 'Legend: ★ key · `std` usual pattern · `uniq` own logic · [color] kind of work · ≈ similar.',
           'colors': 'Colors', 'sims': 'Similar functions', 's': 'std', 'u': 'uniq',
           'uses': 'Used in', 'moved': 'moved', 'reworked': 'Moved and changed',
           'logic': 'logic', 'guard': 'type guard', 'util': 'utility'},
    'ru': {'essence': 'Суть', 'stack': 'Суть стека', 'pr': 'Суть PR', 'key': 'Ключевое', 'split': 'Стандартное / уникальное',
           'legend': 'Обозначения: ★ ключевая · `станд.` стандартный приём · `уник.` своя логика · [цвет] смысл · ≈ похожие.',
           'colors': 'Цвета', 'sims': 'Похожие функции', 's': 'станд.', 'u': 'уник.',
           'uses': 'Используется', 'moved': 'перенос', 'reworked': 'Перенесена и изменена',
           'logic': 'логика', 'guard': 'проверка типа', 'util': 'утилита'},
}


def fn_lines(f, say, cat_name, sim_names, default):
    """A function in the Markdown list: its line, then its explanation, risk and places of use."""
    if unchanged_move(f):
        return [f'  - `{f["name"]}` · {say["moved"]}: `{f["moved"]["from"]}` → `{f["moved"]["to"]}`']
    tags = [f'`{say[f["kind"]]}`', f'[{cat_name[f["cat"]]}]', say[f['type']] if f.get('type') else '', f.get('ext', '')]
    mark = ' ★' if f['key'] else ''
    sim = ' ≈' if f['name'] in sim_names else ''
    out = [f'  - `{f["name"]}`{mark}{sim} — {f["why"]} · ' + ' · '.join(filter(None, tags))]
    if f.get('moved'):
        out.append(f'    - {say["reworked"]}: `{f["moved"]["from"]}` → `{f["moved"]["to"]}`')
    out += [f'    - {f[field]}' for field in ('about', 'without') if f.get(field)]
    uses = f.get('uses')
    if isinstance(uses, list) and uses:
        where = [(u['in'], u['url'], f'#{u["pr"]}' if u['pr'] else default) for u in uses]
        out.append(f'    - {say["uses"]}: ' + ', '.join(f'[{name}]({url}) ({pr})' for name, url, pr in where))
    elif uses:
        out.append(f'    - {say["uses"]}: {uses}')
    return out


def markdown(data):
    say = MD_LABELS['ru' if data.get('lang') == 'ru' else 'en']
    cat_name = {c['id']: c['name'] for c in data['cats']}
    sim_names = {m for s in data.get('sims', []) for m in s['members']}
    out = [f'# {data["title"]}', '', f'**{say["essence"]}:** {data["root"]["essence"]}', '', say['legend'], '',
           f'## {say["colors"]}', '']
    out += [f'- **{c["name"]}** — {c["desc"]}' for c in data['cats']]
    if data.get('sims'):
        out += ['', f'## {say["sims"]}', '']
        out += [f'- ≈ {s["label"]}: ' + ', '.join(f'`{m}`' for m in s['members']) for s in data['sims']]
    for st in data['stacks']:
        ref = ref_of(st)
        gh = f'[{st["gh"]}]({ref["url"]})' if ref and ref['kind'] == 'stack' else st['gh']
        out += ['', f'## {st["name"]} ({gh})', '', f'**{say["stack"]}:** {st["essence"]}']
        for pr in st['prs']:
            fns = [f for g in pr['groups'] for f in g['fns']]
            std = sum(1 for f in fns if f['kind'] == 's')
            where = ' · '.join(filter(None, [f'`{pr["branch"]}`' if pr.get('branch') else '', pr['url']]))
            out += ['', f'### #{pr["n"]} {pr["title"]}', '', where, '',
                    f'**{say["pr"]}:** {pr["essence"]}', '',
                    f'**{say["key"]}:** ' + (', '.join(f'`{f["name"]}`' for f in fns if f['key']) or '—') + '  ',
                    f'**{say["split"]}:** {std} / {len(fns) - std}', '']
            for g in pr['groups']:
                out.append(f'- **{g["name"]}**')
                for f in g['fns']:
                    out += fn_lines(f, say, cat_name, sim_names, data.get('default', 'main'))
    return '\n'.join(out) + '\n'


def category_colors(data):
    return [cat.get('colors', PALETTE[i]) for i, cat in enumerate(data['cats'])]


def data_script(data, palette=False):
    """The data as a script; the bare template also needs the colors, which a built page has in its CSS."""
    full = with_sims(data)
    if palette:
        full['palette'] = category_colors(data)
    return 'window.PR_MAP_DATA = ' + json.dumps(full, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + ';'


def page(data):
    """The page as the Artifact tool takes it: the template with the data, the title and the colors in place."""
    tpl = (HERE / 'template.html').read_text(encoding='utf-8')
    if DATA_TAG not in tpl:
        raise SystemExit('template.html has no data tag: ' + DATA_TAG)
    colors_by_cat = zip(data['cats'], category_colors(data))
    light, dark = [], []
    for cat, (light_color, dark_color) in colors_by_cat:
        light.append(f'  --c-{cat["id"]}: {light_color};')
        dark.append(f'  --c-{cat["id"]}: {dark_color};')
    return (tpl.replace('/*TITLE*/', html.escape(data['title']))
            .replace('/*CAT_LIGHT*/', '\n'.join(light)).replace('/*CAT_DARK*/', '\n'.join(dark))
            .replace(DATA_TAG, f'<script>{data_script(data)}</script>'))


def standalone(fragment, lang='en'):
    """A complete document: the fragment opens with its title, links and one style block, and they go to the head."""
    cut = fragment.index('</style>') + len('</style>')
    return STANDALONE.format(lang=html.escape(lang), head=fragment[:cut].strip(), body=fragment[cut:].strip())


def build(data_path, html_path=None, artifact=None, md=None, data_js=None, log=print):
    """Checks the data and writes the outputs; returns the path of the page to open, if one was written."""
    data_path = Path(data_path)
    data = json.loads(data_path.read_text(encoding='utf-8'))
    errors = check(data)
    if errors:
        raise SystemExit('\n'.join(errors))
    if not (html_path or artifact or md or data_js):
        stem = 'map' if data_path.stem == 'data' else data_path.stem
        html_path, artifact, md = (data_path.with_name(stem + ext) for ext in ('.html', '.artifact.html', '.md'))
    fragment = page(data)
    written = []
    for path, text in ((html_path, standalone(fragment, data.get('lang', 'en'))), (artifact, fragment),
                       (md, markdown(data)), (data_js, data_script(data, palette=True) + '\n')):
        if path:
            Path(path).write_text(text, encoding='utf-8')
            written.append(str(path))
    for line in warnings(data):
        log(f'warning: {line}')
    prs = sum(len(st['prs']) for st in data['stacks'])
    fns = functions(data)
    log(f'ok: {prs} PRs, {len(fns)} functions, details {sum(map(described, fns))}/{len(fns)}, '
        f'{len(data["cats"])} colors, {len(data.get("sims", []))} similarity groups → {", ".join(written)}')
    return Path(html_path) if html_path else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('data')
    ap.add_argument('--html')
    ap.add_argument('--artifact')
    ap.add_argument('--md')
    ap.add_argument('--data-js')
    ap.add_argument('--open', action='store_true', help='open the built page in the browser')
    args = ap.parse_args(argv)
    page_path = build(args.data, args.html, args.artifact, args.md, args.data_js)
    if args.open:
        if not page_path:
            sys.exit('--open needs a page: add --html or drop the output options')
        webbrowser.open(page_path.resolve().as_uri())


if __name__ == '__main__':
    main()
