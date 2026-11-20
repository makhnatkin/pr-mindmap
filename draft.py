#!/usr/bin/env python3
"""Turns raw.json (extract.py) into a mechanical data.json: a map that needs no model to build.

Usage: python3 draft.py raw.json [--out data.json]

The draft takes its structure from the diffs alone: stacks from the branch names of the chain, groups from folders,
colors from packages, "similar" from shared name endings, the purpose of a function from its file. It is a starting
point: the meaning (what each PR and function is for, which functions are key, colors by kind of work) is written
by a person or by the skill on top of it.
"""
import argparse
import json
import re
from collections import Counter, OrderedDict
from pathlib import PurePosixPath

CONVENTIONAL = re.compile(r'^[a-z]+(?:\([^)]*\))?!?:\s*')
CAMEL = re.compile(r'[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])')
MAX_CATS = 10
MAX_GROUPS = 5
MAX_SIMS = 14


def cut(text, limit):
    """`text` in at most `limit` characters, cut at a word."""
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    return (head[:head.rfind(' ')] if ' ' in head[limit // 2:] else head).rstrip(' ,;:·') + '…'


def tail(text, limit):
    """The end of `text` in at most `limit` characters: the file name matters more than the start of its path."""
    return text if len(text) <= limit else '…' + text[-(limit - 1):]


def title_of(pr):
    title = CONVENTIONAL.sub('', pr['title']).strip() or pr['title']
    return title[0].upper() + title[1:]


def essence_of(pr):
    """The first sentence-like line of the PR body, else its title."""
    for line in pr['body'].splitlines():
        line = re.sub(r'[`*_>#]|\[([^\]]*)\]\([^)]*\)', r'\1', line).strip(' -•')
        if len(line) > 20 and not line.startswith(('<!--', '🤖', 'http')):
            return cut(line, 200)
    return cut(title_of(pr), 200)


def area_of(path):
    """The package or the top folder of a file: the unit that a color stands for."""
    parts = PurePosixPath(path).parts
    if len(parts) > 2 and parts[0] in ('packages', 'apps', 'libs', 'services', 'modules', 'crates'):
        return parts[1]
    return parts[0] if len(parts) > 1 else 'root'


def slug(name, taken):
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'area'
    base = base if base[0].isalpha() else f'a-{base}'
    out, i = base, 2
    while out in taken:
        out, i = f'{base}-{i}', i + 1
    taken.add(out)
    return out


def mentioned(name, text):
    """A code name in prose: plain words like `includes` do not count, they are ordinary English."""
    return (len(name) >= 5 and re.search(r'[a-z][A-Z]|_', name) is not None
            and re.search(rf'(?<![\w$]){re.escape(name)}(?![\w$])', text) is not None)


def stack_key(pr):
    """Branches of one stack share everything up to the last word: feat/hdr-title-node, feat/hdr-title-toolbar."""
    head = pr['head']
    return head.rsplit('-', 1)[0] if '-' in head.rsplit('/', 1)[-1] else head


def group_files(files):
    """Folder → files with names, at most MAX_GROUPS folders; the smallest ones merge into the last group."""
    groups = OrderedDict()
    for f in files:
        if f['added'] or f['touched']:
            folder = PurePosixPath(f['path']).parent.name or 'root'
            groups.setdefault(folder, []).append(f)
    if len(groups) > MAX_GROUPS:
        ranked = sorted(groups, key=lambda g: -sum(len(f['added']) + len(f['touched']) for f in groups[g]))
        keep = set(ranked[:MAX_GROUPS - 1])
        merged = OrderedDict((g, fs) for g, fs in groups.items() if g in keep)
        merged['другое'] = [f for g, fs in groups.items() if g not in keep for f in fs]
        groups = merged
    return groups


def similar(fns):
    """Groups of functions from different PRs whose names end with the same words: setTitleAttrs, setImageAttrs."""
    split = {name: CAMEL.findall(re.sub(r'\s*\(.*$', '', name)) for name, _ in fns}
    last = Counter(words[-1].lower() for words in split.values() if words)
    inner = Counter(word.lower() for words in split.values() for word in words[:-1])
    endings = {}
    for name, pr in fns:
        words = split[name]
        for size in (2, 1):
            if len(words) <= size:
                continue
            # One word counts when it names a role (…Values, …Specs), not a thing that names carry anywhere (Title, Image).
            role = size == 2 or inner[words[-1].lower()] * 3 <= last[words[-1].lower()]
            if role and len(''.join(words[-size:])) >= 5:
                endings.setdefault(''.join(w.capitalize() for w in words[-size:]), []).append((name, pr))
    found, used = [], []
    for ending, members in sorted(endings.items(), key=lambda item: (-len(item[1]), -len(item[0]))):
        names = list(OrderedDict.fromkeys(name for name, _ in members))
        if len(names) < 3 or len({pr for _, pr in members}) < 2 or len(names) > 12:
            continue
        # A longer ending with the same members says more than a shorter one.
        if any(set(names) <= other or other <= set(names) for other in used):
            continue
        used.append(set(names))
        found.append({'id': slug(ending, {s['id'] for s in found}), 'label': f'Одинаковое окончание имени: …{ending}', 'members': names})
        if len(found) == MAX_SIMS:
            break
    return found


def draft(raw):
    prs = raw['prs']
    repo = raw['repo'].split('/')[-1]
    counts = Counter(area_of(f['path']) for pr in prs for f in pr['files'] for _ in f['added'] + f['touched'])
    top = [area for area, _ in counts.most_common(MAX_CATS if len(counts) <= MAX_CATS else MAX_CATS - 1)]
    taken = set()
    cat_id = {area: slug(area, taken) for area in top}
    cats = [{'id': cat_id[area], 'name': area, 'desc': f'Функции из {area}: цвет в черновике показывает пакет или папку.'} for area in top]
    if len(counts) > len(top):
        cats.append({'id': slug('other', taken), 'name': 'Другое', 'desc': 'Функции из остальных пакетов и папок.'})
    other = cats[-1]['id']

    seen, all_fns = set(), []

    def card(pr, files):
        text = f'{pr["title"]} {pr["body"]} {" ".join(pr["commits"])}'
        groups = []
        for folder, members in group_files(files).items():
            fns = []
            for f in members:
                for name in f['added'] + f['touched']:
                    changed = name in f['touched']
                    unique = name if name not in seen else f'{name} (#{pr["n"]})'
                    if unique in seen:
                        continue
                    seen.add(unique)
                    file = PurePosixPath(f['path']).name
                    fns.append({
                        'name': unique, 'why': tail(f'изменена · {file}' if changed else file, 50),
                        # Key: a new exported name that the description of the PR talks about.
                        'key': not changed and name in f['exported'] and mentioned(name, text),
                        'kind': 's', 'cat': cat_id.get(area_of(f['path']), other),
                    })
                    all_fns.append((unique, pr['n']))
            if fns:
                groups.append({'name': folder, 'fns': fns})
        return groups

    stacks = []
    if len(prs) == 1:
        # A lone PR: its areas are the branches, each with one card for the same PR.
        pr = prs[0]
        by_area = OrderedDict()
        for f in pr['files']:
            by_area.setdefault(area_of(f['path']), []).append(f)
        for area, files in by_area.items():
            groups = card(pr, files)
            if groups:
                stacks.append({'name': area, 'gh': f'#{pr["n"]}', 'essence': cut(f'Изменения PR в {area}.', 150), 'prs': [{
                    'n': pr['n'], 'url': pr['url'], 'branch': pr['head'], 'title': cut(f'{title_of(pr)}: {area}', 90),
                    'essence': essence_of(pr), 'groups': groups}]})
    else:
        runs = []
        for pr in prs:
            key = stack_key(pr)
            if runs and runs[-1][0] == key:
                runs[-1][1].append(pr)
            else:
                runs.append((key, [pr]))
        for key, members in runs:
            cards = [{'n': pr['n'], 'url': pr['url'], 'branch': pr['head'], 'title': cut(title_of(pr), 90),
                      'essence': essence_of(pr), 'groups': card(pr, pr['files'])} for pr in members]
            cards = [c for c in cards if c['groups']]
            if cards:
                numbers = f'#{cards[0]["n"]}' if len(cards) == 1 else f'#{cards[0]["n"]}–#{cards[-1]["n"]}'
                stacks.append({'name': key.rsplit('/', 1)[-1], 'gh': numbers,
                               'essence': cut('; '.join(c['title'] for c in cards), 150), 'prs': cards})
    if not stacks:
        raise SystemExit('no functions found in the diffs: nothing to draw')
    used = {f['cat'] for st in stacks for pr in st['prs'] for g in pr['groups'] for f in g['fns']}
    numbers = f'#{prs[0]["n"]}' if len(prs) == 1 else f'#{prs[0]["n"]}–#{prs[-1]["n"]}'
    return {
        'title': f'Карта {repo} {numbers}',
        'lang': 'ru',
        'root': {'title': f'{repo} {numbers}',
                 'essence': 'Черновик по диффам: группы — папки, цвета — пакеты, ключевые — упомянутые в описании PR.'},
        'cats': [c for c in cats if c['id'] in used],
        'sims': similar(all_fns),
        'stacks': stacks,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('raw')
    ap.add_argument('--out', default='data.json')
    args = ap.parse_args(argv)
    with open(args.raw, encoding='utf-8') as fh:
        data = draft(json.load(fh))
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    fns = sum(len(g['fns']) for st in data['stacks'] for pr in st['prs'] for g in pr['groups'])
    print(f'ok: {len(data["stacks"])} stacks, {fns} functions → {args.out}')


if __name__ == '__main__':
    main()
