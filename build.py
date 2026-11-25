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
      "path": [{"fn": "uniqueName", "note": "<= 150 chars"}],             # optional: the review order, see below
      "groups": [{"name": "...", "fns": [
        {"name": "uniqueName", "why": "<= 50 chars", "key": true, "kind": "s|u", "cat": "<cat id>",
         "type": "logic | guard | util",   # real work, a type guard, or a small utility
         "about": "<= 500 chars",          # what it is for, in plain words for a reader who does not write code
         "without": "<= 200 chars",        # a sentence on whether the product can do without it, and the risk
         "ext": "YfmTabs",                 # <= 40 chars: its plugin or extension, else its package or module
         "file": "src/a.ts", "line": 12,   # the declaration at the head of the PR (uses.py)
         "code": "https://github.com/…",   # the declaration in the default branch, when the function exists there
         "uses": [{"in": "Caller", "pr": 1480, "url": "https://github.com/…"}],   # the places that use it (uses.py);
                                           # "pr": null for a place the default branch has already
         "moved": {"from": "src/b.ts", "to": "src/a.ts", "changed": true},
                                           # optional: moved from another file; an unchanged move needs nothing else
         "main": true,                     # optional: a function the PR is built around
         "risks": [{"title": "<= 200 chars", "what": "...", "why": "...", "suggestion": "...",
                    "level": "high | mid | low", "at": "src/a.ts:40", "id": 3}]}
                                           # 0-3 risks (analysis.md): `level` how much it costs, `at` a line at the
                                           # head of the PR, `id` the card of the risk in the report (report.py)
      ]}]
    }]
  }],
  "cats": [{"id": "cmd", "name": "Commands", "desc": "Functions that ...",
            "colors": ["#cc4a12", "#ff8a4c"]}],   # 1-10 categories, optional light/dark hex colors
  "sims": [{"id": "values", "label": "...", "members": ["fnA", "fnB"]}],         # groups of very similar functions
  "default": "main",                          # optional: the default branch of the repository (uses.py)
  "report": "report/index.html"               # optional: the report of the risks from the folder of the page (report.py)
}
Function names must be unique across the map: add a short suffix in parentheses when two PRs touch the same name.
The fields after `cat` are optional for the builder; the `ok` line counts the functions that have them: `details`
the card fields, `risks` the risks of analysis.md. A risk with `id` links its card of the report in map.html, which
lies next to the report; map.artifact.html is published apart from it and has no such links. A card the report has
already checked (`f<id>.json` next to it) gives its risk the checked level, `none` for a risk without harm, and the
verdict; the map marks each node with the number of its risks of each level, the ones without harm aside.
A function needs the map functions that name it in their `uses`. The main functions of a PR are the ones with
`main`, else its key functions that no function of the PR needs. `path` lists every function of the PR but the
unchanged moves once, with what to look at on that step; without it the review goes from the functions that need
nothing in the PR to the ones that need them, the main ones last.
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
LIMITS = {'root': 150, 'stack': 150, 'pr': 200, 'why': 50, 'about': 500, 'without': 200, 'ext': 40, 'note': 150,
          'risk': 200, 'risks': 3}
RISK_TEXTS = ('what', 'why', 'suggestion')
RISK_LEVELS = ('high', 'mid', 'low')
# The severity of a card of the review-findings-report skill → the level of its risk.
SEVERITY = {'высокая': 'high', 'средняя': 'mid', 'низкая': 'low', 'нет': 'none'}
AT = re.compile(r'^(\S.*):([1-9]\d*)$')
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


def analysed(f):
    """An unchanged move, or a function with its risks looked at."""
    return unchanged_move(f) or isinstance(f.get('risks'), list)


def risks(data):
    """The risks of the map in its order, each with its PR and function."""
    return [(pr, f, r) for st in data['stacks'] for pr in st['prs'] for g in pr['groups'] for f in g['fns']
            for r in f.get('risks') or [] if isinstance(r, dict)]


def level_of(r):
    """The level of a risk: `none` for a refuted one, `mid` for one without a level."""
    return 'none' if r.get('verdict') == 'refuted' else r.get('level', 'mid')


def risk_counts(found):
    """The number of risks of each level, high first, the ones without harm aside."""
    levels = Counter(map(level_of, found))
    return {level: levels[level] for level in RISK_LEVELS if levels[level]}


def from_report(data, folder):
    """Gives each risk whose card the report in `folder` has checked its level and verdict; returns their number."""
    done = 0
    for _, _, r in risks(data):
        card = folder / f'f{r["id"]}.json' if 'id' in r else None
        if not (card and card.is_file()):
            continue
        try:
            d = json.loads(card.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        if d.get('severity') in SEVERITY:
            r['level'] = SEVERITY[d['severity']]
        if d.get('verdict'):
            r['verdict'] = d['verdict']
        done += 1
    return done


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
    if not isinstance(f.get('main', False), bool):
        yield f'main {f["main"]!r}, expected true or false'
    elif f.get('main') and unchanged_move(f):
        yield 'main on an unchanged move'
    if 'moved' in f and not (isinstance(f['moved'], dict) and isinstance(f['moved'].get('changed', False), bool)
                             and is_text(f['moved'].get('from')) and is_text(f['moved'].get('to'))):
        yield f'moved {f["moved"]!r}, expected {{"from": path, "to": path, "changed": true | false}}'
    yield from risk_problems(f)


def risk_problems(f):
    if 'risks' not in f:
        return
    found = f['risks']
    if not (isinstance(found, list) and all(isinstance(r, dict) and is_text(r.get('title'))
                                            and set(r) <= {'title', *RISK_TEXTS, 'level', 'at', 'id'} for r in found)):
        yield 'risks: expected a list of {"title", "what", "why", "suggestion": text, "level", "at": "path:line"}'
        return
    if len(found) > LIMITS['risks']:
        yield f'risks: {len(found)} > {LIMITS["risks"]}'
    for r in found:
        if len(r['title']) > LIMITS['risk']:
            yield f'risk {len(r["title"])} > {LIMITS["risk"]} «{r["title"][:40]}…»'
        yield from (f'risk «{r["title"][:40]}»: {key} is empty' for key in RISK_TEXTS if key in r and not is_text(r[key]))
        if 'level' in r and r['level'] not in RISK_LEVELS:
            yield f'risk «{r["title"][:40]}»: level {r["level"]!r}, expected one of {", ".join(RISK_LEVELS)}'
        if 'at' in r and not (isinstance(r['at'], str) and AT.match(r['at'])):
            yield f'risk at {r["at"]!r}, expected "path:line"'
        if 'id' in r and not is_count(r['id'], 1):
            yield f'risk «{r["title"][:40]}»: id {r["id"]!r}, expected a number from 1'


def steps_of(pr):
    """The functions of a PR that a review goes through: all but the unchanged moves."""
    return [f for g in pr['groups'] for f in g['fns'] if not unchanged_move(f)]


def path_problems(pr):
    if 'path' not in pr:
        return
    path = pr['path']
    if not (isinstance(path, list) and all(isinstance(step, dict) and is_text(step.get('fn')) for step in path)):
        yield 'expected a list of {"fn": name, "note": text}'
        return
    for step in path:
        note = step.get('note', '')
        if not isinstance(note, str):
            yield f'{step["fn"]}: note {note!r} is not text'
        elif len(note) > LIMITS['note']:
            yield f'{step["fn"]}: note {len(note)} > {LIMITS["note"]}'
    listed = Counter(step['fn'] for step in path)
    names = [f['name'] for f in steps_of(pr)]
    yield from (f'{name} is not a function of the PR to review' for name in listed if name not in names)
    yield from (f'{name} is listed {n} times' for name, n in listed.items() if n > 1)
    yield from (f'{name} is missing' for name in names if name not in listed)


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
            errors += [f'#{pr["n"]}: path: {problem}' for problem in path_problems(pr)]
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
    cards = Counter(r.get('id') for _, _, r in risks(data) if 'id' in r)
    errors += [f'risk id {i!r} is on {n} risks' for i, n in cards.items() if n > 1]
    if 'report' in data and not is_text(data['report']):
        errors.append('report: expected the path of the report from the folder of the page')
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
    out = [f'cat {c["id"]!r} has no functions' for c in data['cats'] if c['id'] not in used]
    needs = needs_of(data)
    for st in data['stacks']:
        for pr in st['prs']:
            seen = set()
            for step in pr.get('path', []):
                later = [name for name in needs.get(step['fn'], []) if name in {f['name'] for f in steps_of(pr)} - seen]
                if later:
                    out.append(f'#{pr["n"]}: path: {step["fn"]} comes before {", ".join(later)} it needs')
                seen.add(step['fn'])
    return out


def needs_of(data):
    """Name → the map functions it needs: the ones whose `uses` name it."""
    names = {f['name'] for f in functions(data)}
    needs = {}
    for f in functions(data):
        for u in f['uses'] if isinstance(f.get('uses'), list) else []:
            if u['in'] in names and u['in'] != f['name']:
                found = needs.setdefault(u['in'], [])
                if f['name'] not in found:
                    found.append(f['name'])
    return needs


def main_of(pr, needs):
    """The functions the PR is built around: the ones marked `main`, else its key functions no function of it needs."""
    fns = steps_of(pr)
    marked = {f['name'] for f in fns if f.get('main')}
    if marked:
        return marked
    needed = {name for f in fns for name in needs.get(f['name'], [])}
    return {f['name'] for f in fns if f['key'] and f['name'] not in needed}


def review_order(pr, needs):
    """The steps of a review of the PR: its `path`, else each function after the ones of the PR it needs, in map
    order, the main ones as late as they can go."""
    if 'path' in pr:
        return [{'fn': step['fn'], 'note': step.get('note', '')} for step in pr['path']]
    main = main_of(pr, needs)
    rank = {f['name']: i for i, f in enumerate(steps_of(pr))}
    wait = {name: {other for other in needs.get(name, []) if other in rank and other != name} for name in rank}
    order = []
    while wait:
        # Functions that need each other leave none ready: the one that waits for the fewest goes first.
        ready = [name for name, rest in wait.items() if not rest] or list(wait)
        step = min(ready, key=lambda name: (name in main, len(wait[name]), rank[name]))
        order.append({'fn': step, 'note': ''})
        del wait[step]
        for rest in wait.values():
            rest.discard(step)
    return order


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


def at_link(pr, at):
    """`path:line` of a risk in the diff of `pr`."""
    path, line = AT.match(at).groups()
    return diff_link(pr, {'file': path, 'line': int(line)})


def page_data(data):
    """A copy of the data for the page: each function with its similarity groups, its place in the diff of its PR,
    the functions it needs, its `main` and its risks with their lines in the diff and their cards in the report; each
    PR with its review order; each stack with its GitHub page."""
    of = {}
    for s in data.get('sims', []):
        for member in s['members']:
            of.setdefault(member, []).append(s['id'])
    needs, report = needs_of(data), data.get('report')

    def risk_data(pr, r):
        out = {**r, 'url': at_link(pr, r['at'])} if r.get('at') else dict(r)
        if report and 'id' in r:
            out['card'] = f'{report}?only={r["id"]}'
        return out

    def fn_data(pr, f, main):
        out = {**f, 'sims': of.get(f['name'], []), 'diff': diff_link(pr, f), 'needs': needs.get(f['name'], []),
               'main': f['name'] in main}
        if 'risks' in f:
            out['risks'] = [risk_data(pr, r) for r in f['risks']]
        return out

    def pr_data(pr):
        main = main_of(pr, needs)
        return {**pr, 'order': review_order(pr, needs), 'groups': [
            {**g, 'fns': [fn_data(pr, f, main) for f in g['fns']]} for g in pr['groups']]}

    return {**data, 'sims': data.get('sims', []),
            'stacks': [{**st, 'ref': ref_of(st), 'prs': [pr_data(pr) for pr in st['prs']]} for st in data['stacks']]}


MD_LABELS = {
    'en': {'essence': 'Essence', 'stack': 'Stack essence', 'pr': 'PR essence', 'key': 'Key', 'split': 'Standard / unique',
           'legend': 'Legend: ★ key · ◆ main · `std` usual pattern · `uniq` own logic · [color] kind of work · ≈ similar.',
           'colors': 'Colors', 'sims': 'Similar functions', 's': 'std', 'u': 'uniq',
           'uses': 'Used in', 'moved': 'moved', 'reworked': 'Moved and changed',
           'logic': 'logic', 'guard': 'type guard', 'util': 'utility', 'order': 'Review order', 'risk': 'Risk', 'card': 'report',
           'risks': 'Risks', 'refuted': 'refuted', 'levels': {'high': 'high', 'mid': 'medium', 'low': 'low', 'none': 'no harm'}},
    'ru': {'essence': 'Суть', 'stack': 'Суть стека', 'pr': 'Суть PR', 'key': 'Ключевое', 'split': 'Стандартное / уникальное',
           'legend': 'Обозначения: ★ ключевая · ◆ главная · `станд.` стандартный приём · `уник.` своя логика · [цвет] смысл · ≈ похожие.',
           'colors': 'Цвета', 'sims': 'Похожие функции', 's': 'станд.', 'u': 'уник.',
           'uses': 'Используется', 'moved': 'перенос', 'reworked': 'Перенесена и изменена',
           'logic': 'логика', 'guard': 'проверка типа', 'util': 'утилита', 'order': 'Порядок анализа', 'risk': 'Риск', 'card': 'доклад',
           'risks': 'Риски', 'refuted': 'опровергнут',
           'levels': {'high': 'высокая', 'mid': 'средняя', 'low': 'низкая', 'none': 'без вреда'}},
}


def fn_lines(f, say, cat_name, sim_names, default, pr, report=None):
    """A function in the Markdown list: its line, then its explanation, what it costs to go without it, its risks
    with their cards of the report and its places of use."""
    if unchanged_move(f):
        return [f'  - `{f["name"]}` · {say["moved"]}: `{f["moved"]["from"]}` → `{f["moved"]["to"]}`']
    tags = [f'`{say[f["kind"]]}`', f'[{cat_name[f["cat"]]}]', say[f['type']] if f.get('type') else '', f.get('ext', '')]
    mark = ' ★' if f['key'] else ''
    sim = ' ≈' if f['name'] in sim_names else ''
    out = [f'  - `{f["name"]}`{mark}{sim} — {f["why"]} · ' + ' · '.join(filter(None, tags))]
    if f.get('moved'):
        out.append(f'    - {say["reworked"]}: `{f["moved"]["from"]}` → `{f["moved"]["to"]}`')
    out += [f'    - {f[field]}' for field in ('about', 'without') if f.get(field)]
    for r in f.get('risks', []):
        at = f' · [{r["at"]}]({at_link(pr, r["at"])})' if r.get('at') else ''
        card = f' · [{say["card"]} № {r["id"]}]({report}#f{r["id"]})' if report and 'id' in r else ''
        level = say['refuted'] if r.get('verdict') == 'refuted' else say['levels'].get(r.get('level'))
        out.append(f'    - {say["risk"]}{f" ({level})" if level else ""}: {r["title"]}{at}{card}')
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
    needs = needs_of(data)
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
                    f'**{say["split"]}:** {std} / {len(fns) - std}']
            counts = risk_counts([r for f in fns for r in f.get('risks') or []])
            if counts:
                out[-1] += '  '
                out.append(f'**{say["risks"]}:** ' + ', '.join(f'{say["levels"][lv]} {n}' for lv, n in counts.items()))
            out.append('')
            for g in pr['groups']:
                out.append(f'- **{g["name"]}**')
                for f in g['fns']:
                    out += fn_lines(f, say, cat_name, sim_names, data.get('default', 'main'), pr, data.get('report'))
            by_name, main = {f['name']: f for f in fns}, main_of(pr, needs)
            out += ['', f'**{say["order"]}:**', '']
            for i, step in enumerate(review_order(pr, needs), 1):
                f = by_name[step['fn']]
                where = f' · `{f["file"]}`' if f.get('file') else ''
                out.append(f'{i}. `{f["name"]}`{" ◆" if f["name"] in main else ""} — {step["note"] or f["why"]}{where}')
    return '\n'.join(out) + '\n'


def category_colors(data):
    return [cat.get('colors', PALETTE[i]) for i, cat in enumerate(data['cats'])]


def data_script(data, palette=False):
    """The data as a script; the bare template also needs the colors, which a built page has in its CSS."""
    full = page_data(data)
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
    if data.get('report'):
        from_report(data, data_path.parent / Path(data['report']).parent)
    if not (html_path or artifact or md or data_js):
        stem = 'map' if data_path.stem == 'data' else data_path.stem
        html_path, artifact, md = (data_path.with_name(stem + ext) for ext in ('.html', '.artifact.html', '.md'))
    fragment = page(data)
    published = page({k: v for k, v in data.items() if k != 'report'}) if artifact and 'report' in data else fragment
    written = []
    for path, text in ((html_path, standalone(fragment, data.get('lang', 'en'))), (artifact, published),
                       (md, markdown(data)), (data_js, data_script(data, palette=True) + '\n')):
        if path:
            Path(path).write_text(text, encoding='utf-8')
            written.append(str(path))
    for line in warnings(data):
        log(f'warning: {line}')
    prs = sum(len(st['prs']) for st in data['stacks'])
    fns = functions(data)
    paths = sum('path' in pr for st in data['stacks'] for pr in st['prs'])
    found = [r for _, _, r in risks(data)]
    levels = ' · '.join(f'{lv} {n}' for lv, n in risk_counts(found).items())
    log(f'ok: {prs} PRs, {len(fns)} functions, details {sum(map(described, fns))}/{len(fns)}, '
        f'risks {sum(map(analysed, fns))}/{len(fns)}{f" ({levels})" if levels else ""}, '
        f'report {sum("id" in r for r in found)}/{len(found)}, '
        f'paths {paths}/{prs}, '
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
