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
  "title": "Карта ...",                       # page title, a name of 2-4 words
  "lang": "ru",                               # optional, the language of the page
  "root": {"title": "...", "essence": "..."},  # essence <= 150 chars
  "stacks": [{
    "name": "...", "gh": "stack 1491 | без stack", "essence": "...",   # essence <= 150
    "prs": [{
      "n": 1475, "url": "https://github.com/o/r/pull/1475", "branch": "feat/x",
      "title": "...", "essence": "...",                                   # essence <= 200
      "groups": [{"name": "...", "fns": [
        {"name": "uniqueName", "why": "<= 50 chars", "key": true, "kind": "s|u", "cat": "<cat id>"}
      ]}]
    }]
  }],
  "cats": [{"id": "cmd", "name": "Команды", "desc": "Функции, которые ..."}],     # 1-10 colors, in legend order
  "sims": [{"id": "values", "label": "...", "members": ["fnA", "fnB"]}]          # groups of very similar functions
}
Function names must be unique across the map: add a short suffix in parentheses when two PRs touch the same name.
A category id becomes a part of a CSS name: lowercase Latin letters, digits and hyphens, starting with a letter.
"""
import argparse
import html
import json
import re
import sys
import webbrowser
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIMITS = {'root': 150, 'stack': 150, 'pr': 200, 'why': 50}
CAT_ID = re.compile(r'^[a-z][a-z0-9-]*$')
# Light and dark values of the category colors, in legend order.
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
            if not str(pr['url']).startswith('http'):
                errors.append(f'#{pr["n"]}: url {pr["url"]!r} is not a link')
            if not pr['groups']:
                errors.append(f'#{pr["n"]}: no groups')
            for g in pr['groups']:
                if not g['fns']:
                    errors.append(f'#{pr["n"]}: group {g["name"]!r} is empty')
                for f in g['fns']:
                    if len(f['why']) > LIMITS['why']:
                        errors.append(f'{f["name"]}: why {len(f["why"])} > {LIMITS["why"]} «{f["why"]}»')
                    if f['kind'] not in ('s', 'u'):
                        errors.append(f'{f["name"]}: kind {f["kind"]!r}, expected "s" or "u"')
                    if f['cat'] not in cats:
                        errors.append(f'{f["name"]}: unknown cat {f["cat"]!r}')
                    if not isinstance(f['key'], bool):
                        errors.append(f'{f["name"]}: key {f["key"]!r}, expected true or false')
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


def with_sims(data):
    """A copy of the data in which each function names the similarity groups it belongs to."""
    of = {}
    for s in data.get('sims', []):
        for member in s['members']:
            of.setdefault(member, []).append(s['id'])
    return {**data, 'sims': data.get('sims', []), 'stacks': [{**st, 'prs': [{**pr, 'groups': [
        {**g, 'fns': [{**f, 'sims': of.get(f['name'], [])} for f in g['fns']]} for g in pr['groups']]}
        for pr in st['prs']]} for st in data['stacks']]}


def markdown(data):
    cat_name = {c['id']: c['name'] for c in data['cats']}
    sim_names = {m for s in data.get('sims', []) for m in s['members']}
    out = [f'# {data["title"]}', '', f'**Суть стека:** {data["root"]["essence"]}', '',
           'Обозначения: ★ ключевая · `станд.` стандартный приём · `уник.` своя логика · [цвет] смысл · ≈ похожие.', '',
           '## Цвета', '']
    out += [f'- **{c["name"]}** — {c["desc"]}' for c in data['cats']]
    if data.get('sims'):
        out += ['', '## Похожие функции', '']
        out += [f'- ≈ {s["label"]}: ' + ', '.join(f'`{m}`' for m in s['members']) for s in data['sims']]
    for st in data['stacks']:
        out += ['', f'## {st["name"]} ({st["gh"]})', '', f'**Суть стека:** {st["essence"]}']
        for pr in st['prs']:
            fns = [f for g in pr['groups'] for f in g['fns']]
            std = sum(1 for f in fns if f['kind'] == 's')
            where = ' · '.join(filter(None, [f'`{pr["branch"]}`' if pr.get('branch') else '', pr['url']]))
            out += ['', f'### #{pr["n"]} {pr["title"]}', '', where, '',
                    f'**Суть PR:** {pr["essence"]}', '',
                    '**Ключевое:** ' + (', '.join(f'`{f["name"]}`' for f in fns if f['key']) or '—') + '  ',
                    f'**Стандартное / уникальное:** {std} / {len(fns) - std}', '']
            for g in pr['groups']:
                out.append(f'- **{g["name"]}**')
                for f in g['fns']:
                    mark = ' ★' if f['key'] else ''
                    sim = ' ≈' if f['name'] in sim_names else ''
                    kind = 'станд.' if f['kind'] == 's' else 'уник.'
                    out.append(f'  - `{f["name"]}`{mark} — {f["why"]} · `{kind}` · [{cat_name[f["cat"]]}]{sim}')
    return '\n'.join(out) + '\n'


def data_script(data, palette=False):
    """The data as a script; the bare template also needs the colors, which a built page has in its CSS."""
    full = with_sims(data)
    if palette:
        full['palette'] = PALETTE[:len(data['cats'])]
    return 'window.PR_MAP_DATA = ' + json.dumps(full, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + ';'


def page(data):
    """The page as the Artifact tool takes it: the template with the data, the title and the colors in place."""
    tpl = (HERE / 'template.html').read_text(encoding='utf-8')
    if DATA_TAG not in tpl:
        raise SystemExit('template.html has no data tag: ' + DATA_TAG)
    light = '\n'.join(f'  --c-{c["id"]}: {PALETTE[i][0]};' for i, c in enumerate(data['cats']))
    dark = '\n'.join(f'  --c-{c["id"]}: {PALETTE[i][1]};' for i, c in enumerate(data['cats']))
    return (tpl.replace('/*TITLE*/', html.escape(data['title']))
            .replace('/*CAT_LIGHT*/', light).replace('/*CAT_DARK*/', dark)
            .replace(DATA_TAG, f'<script>{data_script(data)}</script>'))


def standalone(fragment, lang='ru'):
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
    for path, text in ((html_path, standalone(fragment, data.get('lang', 'ru'))), (artifact, fragment),
                       (md, markdown(data)), (data_js, data_script(data, palette=True) + '\n')):
        if path:
            Path(path).write_text(text, encoding='utf-8')
            written.append(str(path))
    for line in warnings(data):
        log(f'warning: {line}')
    prs = sum(len(st['prs']) for st in data['stacks'])
    log(f'ok: {prs} PRs, {len(functions(data))} functions, {len(data["cats"])} colors, '
        f'{len(data.get("sims", []))} similarity groups → {", ".join(written)}')
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
