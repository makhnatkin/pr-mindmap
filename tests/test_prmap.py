#!/usr/bin/env python3
"""Tests of the builder, the extractor and the draft. Run: python3 -m unittest discover -s tests -v

The browser test needs Google Chrome or Chromium and is skipped without one; the syntax test needs node.
"""
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build  # noqa: E402
import draft  # noqa: E402
import extract  # noqa: E402
import uses  # noqa: E402

EXAMPLE = ROOT / 'example' / 'banner.json'
CHROME = next((p for p in (
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    shutil.which('google-chrome'), shutil.which('chromium'), shutil.which('chromium-browser'),
) if p and Path(p).exists()), None)

DIFF = '''diff --git a/packages/ui/src/Panel.tsx b/packages/ui/src/Panel.tsx
--- a/packages/ui/src/Panel.tsx
+++ b/packages/ui/src/Panel.tsx
@@ -1,3 +1,9 @@ import React from 'react';
+export function Panel({children}: Props) {
+    return <div>{children}</div>;
+}
+const usePanelState = () => useState(false);
+export const openPanel = (id: string): Command => (state) => true;
+export type PanelProps = {children: ReactNode};
+interface Internal {
@@ -40,6 +46,7 @@ function closePanel(view: EditorView) {
     view.focus();
+    view.dispatch(tr);
 }
diff --git a/packages/ui/src/Panel.test.tsx b/packages/ui/src/Panel.test.tsx
--- a/packages/ui/src/Panel.test.tsx
+++ b/packages/ui/src/Panel.test.tsx
@@ -0,0 +1,3 @@
+function helper() {}
diff --git a/tools/gen.py b/tools/gen.py
--- a/tools/gen.py
+++ b/tools/gen.py
@@ -0,0 +1,4 @@
+def make_map(data):
+    return data
+class Builder:
+    def run(self):
'''


def example():
    return json.loads(EXAMPLE.read_text(encoding='utf-8'))


def raw_pr(n, head, files, title='feat(x): add a thing', body=''):
    return {'n': n, 'url': f'https://github.com/o/r/pull/{n}', 'title': title, 'body': body, 'base': 'main', 'head': head,
            'state': 'OPEN', 'draft': False, 'commits': [title], 'additions': 1, 'deletions': 0,
            'files': [{'path': p, 'additions': 1, 'deletions': 0, 'added': a, 'exported': e, 'touched': t, 'types': []} for p, a, e, t in files]}


class Check(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(build.check(example()), [])
        self.assertEqual(build.warnings(example()), [])

    def broken(self, change):
        data = example()
        change(data)
        return '\n'.join(build.check(data))

    def test_limits(self):
        fn = lambda d: d['stacks'][0]['prs'][0]['groups'][0]['fns'][0]
        self.assertIn('why 60 > 50', self.broken(lambda d: fn(d).update(why='x' * 60)))
        self.assertIn('essence 201 > 200', self.broken(lambda d: d['stacks'][0]['prs'][0].update(essence='x' * 201)))
        self.assertIn('essence 151 > 150', self.broken(lambda d: d['stacks'][0].update(essence='x' * 151)))
        self.assertIn("state 'wip'", self.broken(lambda d: d['stacks'][0]['prs'][0].update(state='wip')))
        self.assertIn('root essence', self.broken(lambda d: d['root'].update(essence='x' * 151)))

    def test_references(self):
        fn = lambda d: d['stacks'][0]['prs'][0]['groups'][0]['fns'][0]
        self.assertIn("unknown cat 'nope'", self.broken(lambda d: fn(d).update(cat='nope')))
        self.assertIn("kind 'x'", self.broken(lambda d: fn(d).update(kind='x')))
        self.assertIn('duplicate function names', self.broken(lambda d: fn(d).update(name=d['stacks'][1]['prs'][0]['groups'][0]['fns'][0]['name'])))
        self.assertIn("unknown ['ghost']", self.broken(lambda d: d['sims'][0]['members'].append('ghost')))

    def test_category_ids_are_css_names(self):
        self.assertIn('cat id', self.broken(lambda d: d['cats'][0].update(id='My Cat')))
        self.assertIn('duplicate cat id', self.broken(lambda d: d['cats'][1].update(id=d['cats'][0]['id'])))

    def test_structure(self):
        self.assertIn('is empty', self.broken(lambda d: d['stacks'][0]['prs'][0]['groups'][0].update(fns=[])))
        self.assertIn('no PRs', self.broken(lambda d: d['stacks'][0].update(prs=[])))
        self.assertIn('missing or malformed field', self.broken(lambda d: d['stacks'][0].pop('essence')))

    def test_unused_category_is_a_warning(self):
        data = example()
        used = data['cats'][0]['id']
        for f in build.functions(data):
            if f['cat'] == data['cats'][1]['id']:
                f['cat'] = used
        self.assertEqual(build.check(data), [])
        self.assertEqual(build.warnings(data), [f"cat {data['cats'][1]['id']!r} has no functions"])


class Build(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def test_default_outputs(self):
        shutil.copy(EXAMPLE, self.dir / 'data.json')
        page = build.build(self.dir / 'data.json', log=lambda *_: None)
        self.assertEqual(page, self.dir / 'map.html')
        standalone, fragment, md = (self.dir / name for name in ('map.html', 'map.artifact.html', 'map.md'))
        self.assertTrue(standalone.read_text(encoding='utf-8').startswith('<!doctype html>'))
        self.assertTrue(fragment.read_text(encoding='utf-8').startswith('<title>'))
        for text in (standalone.read_text(encoding='utf-8'), fragment.read_text(encoding='utf-8')):
            self.assertIn('window.PR_MAP_DATA = {', text)
            for leftover in ('/*TITLE*/', '/*CAT_LIGHT*/', '/*CAT_DARK*/', build.DATA_TAG):
                self.assertNotIn(leftover, text)
        listing = md.read_text(encoding='utf-8')
        for st in example()['stacks']:
            for pr in st['prs']:
                self.assertIn(f'### #{pr["n"]} ', listing)

    def test_named_after_the_data_file(self):
        shutil.copy(EXAMPLE, self.dir / 'banner.json')
        self.assertEqual(build.build(self.dir / 'banner.json', log=lambda *_: None), self.dir / 'banner.html')

    def test_only_what_was_asked(self):
        build.build(EXAMPLE, data_js=self.dir / 'map-data.js', log=lambda *_: None)
        self.assertEqual([p.name for p in self.dir.iterdir()], ['map-data.js'])
        self.assertIn('"palette":', (self.dir / 'map-data.js').read_text(encoding='utf-8'))

    def test_explicit_colors_stay_with_the_category(self):
        data = example()
        cat = data['cats'][0]
        cat['colors'] = ['#2468ac', '#8aceef']
        data['cats'].reverse()
        data_path = self.dir / 'data.json'
        data_path.write_text(json.dumps(data), encoding='utf-8')

        build.build(data_path, log=lambda *_: None)
        for path in (self.dir / 'map.html', self.dir / 'map.artifact.html'):
            page = path.read_text(encoding='utf-8')
            for color in cat['colors']:
                self.assertIn(f'--c-{cat["id"]}: {color};', page)

        data_js = self.dir / 'map-data.js'
        build.build(data_path, data_js=data_js, log=lambda *_: None)
        script = data_js.read_text(encoding='utf-8').strip()
        embedded = json.loads(script.removeprefix('window.PR_MAP_DATA = ').removesuffix(';'))
        self.assertEqual(embedded['palette'][0], list(build.PALETTE[0]))
        self.assertEqual(embedded['palette'][-1], cat['colors'])

    def test_invalid_category_colors(self):
        data = example()
        for colors in (None, '#2468ac', ['#2468ac'], ['#2468ac', 'red;']):
            with self.subTest(colors=colors):
                data['cats'][0]['colors'] = colors
                self.assertIn('colors must contain two #RRGGBB values', '\n'.join(build.check(data)))

    def test_invalid_data_stops_the_build(self):
        data = example()
        data['cats'][0]['id'] = 'Bad Id'
        (self.dir / 'data.json').write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(SystemExit):
            build.build(self.dir / 'data.json', log=lambda *_: None)
        self.assertEqual([p.name for p in self.dir.iterdir()], ['data.json'])

    def test_input_is_not_changed(self):
        data = example()
        before = copy.deepcopy(data)
        build.with_sims(data)
        build.markdown(data)
        self.assertEqual(data, before)

    def test_stack_links(self):
        st = lambda gh, *ns: {'gh': gh, 'prs': [{'n': n, 'url': f'https://github.com/o/r/pull/{n}'} for n in ns]}
        self.assertEqual(build.ref_of(st('stack 1491', 1, 2)), {'kind': 'stack', 'n': 1491, 'url': 'https://github.com/o/r/stack/1491'})
        self.assertEqual(build.ref_of(st('no stack', 7)), {'kind': 'pr', 'n': 7, 'url': 'https://github.com/o/r/pull/7'})
        self.assertIsNone(build.ref_of(st('#1–#2', 1, 2)))
        self.assertIn('(https://github.com/gravity-ui/markdown-editor/stack/1491)', build.markdown(example()))

    def test_markdown_speaks_the_language_of_the_map(self):
        self.assertIn('## Colors', build.markdown(example()))
        self.assertIn('## Цвета', build.markdown({**example(), 'lang': 'ru'}))

    def test_script_cannot_be_closed_by_the_data(self):
        data = example()
        data['root']['essence'] = '</script><b>x'
        self.assertNotIn('</script><b>', build.data_script(data))

    @unittest.skipUnless(shutil.which('node'), 'needs node')
    def test_page_script_parses(self):
        fragment = build.page(example())
        script = fragment[fragment.rindex('<script>') + len('<script>'):fragment.rindex('</script>')]
        path = self.dir / 'page.js'
        path.write_text(script, encoding='utf-8')
        subprocess.run(['node', '--check', str(path)], check=True, capture_output=True)

    @unittest.skipUnless(CHROME, 'needs Chrome or Chromium')
    def test_page_renders_in_a_browser(self):
        page = self.dir / 'map.html'
        build.build(EXAMPLE, page, log=lambda *_: None)
        dom = subprocess.run([CHROME, '--headless=new', '--disable-gpu', f'--user-data-dir={self.dir / "profile"}',
                              '--window-size=1600,1000', '--virtual-time-budget=4000', '--dump-dom', page.as_uri()],
                             capture_output=True, text=True, timeout=120).stdout
        data = example()
        prs = sum(len(st['prs']) for st in data['stacks'])
        self.assertEqual(dom.count('class="node pr"'), prs)
        self.assertEqual(dom.count('class="node stack"'), len(data['stacks']))
        self.assertEqual(len(re.findall(r'<button class="fn"', dom)), len(build.functions(data)))
        self.assertIn(f'{len(build.functions(data))}/{len(build.functions(data))} fn', dom)
        edges = dom[dom.index('id="edges"'):dom.index('id="links"')]
        self.assertGreater(edges.count('<path'), prs)
        self.assertRegex(dom, r'id="canvas" style="transform: translate\([-\d.]+px, [-\d.]+px\) scale\((?:0?\.\d+|1)\)')


class Names(unittest.TestCase):
    def test_added_exported_and_touched(self):
        found = extract.names(DIFF)
        panel = found['packages/ui/src/Panel.tsx']
        self.assertEqual(panel['added'], ['Panel', 'usePanelState', 'openPanel'])
        self.assertEqual(panel['exported'], ['Panel', 'openPanel'])
        self.assertEqual(panel['touched'], ['closePanel'])
        self.assertEqual(panel['types'], ['PanelProps', 'Internal'])

    def test_tests_are_skipped_and_python_is_read(self):
        found = extract.names(DIFF)
        self.assertNotIn('packages/ui/src/Panel.test.tsx', found)
        self.assertEqual(found['tools/gen.py']['added'], ['make_map', 'Builder', 'run'])

    def test_keywords_are_not_names(self):
        self.assertIsNone(extract.definition('    if (ready) {'))
        self.assertIsNone(extract.definition('    constructor(view: EditorView) {'))
        self.assertEqual(extract.definition('    private renderAttrs() {'), 'renderAttrs')

    def test_url(self):
        self.assertEqual(extract.URL.search('https://github.com/o/r/pull/12/files').groups(), ('o/r', '12'))
        self.assertEqual(extract.STACK_URL.search('https://github.com/o/r/stack/1491').groups(), ('o/r', '1491'))


class Draft(unittest.TestCase):
    def raw(self):
        return {'repo': 'o/r', 'default': 'main', 'prs': [
            raw_pr(1, 'feat/hdr-title-node', [('packages/ui/src/title/node.ts', ['setTitleAttrs', 'titleNode'], ['setTitleAttrs'], [])],
                   body='Adds `setTitleAttrs` for the title of the banner, with its size and color.'),
            raw_pr(2, 'feat/hdr-title-toolbar', [('packages/ui/src/title/toolbar.tsx', ['TitleToolbar'], ['TitleToolbar'], ['titleNode'])]),
            raw_pr(3, 'feat/hdr-image-node', [('packages/core/src/image/node.ts', ['setImageAttrs', 'titleNode'], ['setImageAttrs'], [])]),
            raw_pr(4, 'feat/layout', [('packages/core/src/layout.ts', ['setLayoutAttrs'], [], [])]),
        ]}

    def test_draft_builds(self):
        data = draft.draft(self.raw())
        self.assertEqual(build.check(data), [])
        self.assertEqual([st['name'] for st in data['stacks']], ['hdr-title', 'hdr-image', 'layout'])
        self.assertEqual([len(st['prs']) for st in data['stacks']], [2, 1, 1])
        self.assertEqual({c['name'] for c in data['cats']}, {'ui', 'core'})

    def test_names_stay_unique_and_changed_ones_are_marked(self):
        fns = build.functions(draft.draft(self.raw()))
        names = [f['name'] for f in fns]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('titleNode (#2)', names)
        self.assertTrue(next(f for f in fns if f['name'] == 'titleNode (#2)')['why'].startswith('changed'))

    def test_key_is_what_the_description_names(self):
        fns = {f['name']: f for f in build.functions(draft.draft(self.raw()))}
        self.assertTrue(fns['setTitleAttrs']['key'])
        self.assertFalse(fns['titleNode']['key'])

    def test_similar_by_name_ending(self):
        sims = draft.draft(self.raw())['sims']
        self.assertTrue(any(set(s['members']) == {'setTitleAttrs', 'setImageAttrs', 'setLayoutAttrs'} for s in sims))

    def test_plain_words_are_not_key(self):
        self.assertFalse(draft.mentioned('includes', 'the list includes values'))
        self.assertTrue(draft.mentioned('syncDomAttrs', 'share `syncDomAttrs` between views'))
        self.assertFalse(draft.mentioned('setAttrs', 'calls resetAttrs twice'))

    def test_a_thing_in_a_name_is_not_a_similarity(self):
        fns = [('headerTitle', 1), ('pageTitle', 2), ('cardTitle', 3), ('titleNode', 1), ('titleView', 2), ('titlePlugin', 3)]
        self.assertEqual(draft.similar(fns), [])

    def test_lone_pr_branches_by_area(self):
        raw = {'repo': 'o/r', 'default': 'main', 'prs': [raw_pr(7, 'fix/x', [
            ('packages/ui/src/a.ts', ['alpha'], [], []), ('packages/core/src/b.ts', ['beta'], [], [])])]}
        data = draft.draft(raw)
        self.assertEqual(build.check(data), [])
        self.assertEqual([st['name'] for st in data['stacks']], ['ui', 'core'])
        self.assertEqual({pr['n'] for st in data['stacks'] for pr in st['prs']}, {7})

    def test_texts_fit_the_limits(self):
        raw = self.raw()
        raw['prs'][0]['body'] = 'x ' * 400
        raw['prs'][0]['title'] = 'feat: ' + 'long title ' * 30
        self.assertEqual(build.check(draft.draft(raw)), [])


MOVE_DIFF = '''diff --git a/src/old.ts b/src/old.ts
--- a/src/old.ts
+++ b/src/old.ts
@@ -1,9 +1,3 @@
-export function shared(a: number) {
-    return a + 1;
-}
-function reworked(a: number) {
-    return a;
-}
 function stays() {}
diff --git a/src/new.ts b/src/new.ts
new file mode 100644
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,6 @@
+function shared(a: number) {
+    return a + 1;
+}
+export function reworked(a: number) {
+    return a * 2;
+}
diff --git a/src/reorder.ts b/src/reorder.ts
--- a/src/reorder.ts
+++ b/src/reorder.ts
@@ -1,6 +1,6 @@
-function first() {
-    return 1;
-}
 function second() {}
+function first() {
+    return 1;
+}
diff --git a/src/ext/Old.tsx b/src/ui/Switch.tsx
similarity index 60%
rename from src/ext/Old.tsx
rename to src/ui/Switch.tsx
--- a/src/ext/Old.tsx
+++ b/src/ui/Switch.tsx
@@ -1,3 +1,3 @@
-export function Switch({label}) {
+export function Switch({label, onUpdate}) {
     return null;
 }
diff --git a/src/gone.ts b/src/gone.ts
deleted file mode 100644
--- a/src/gone.ts
+++ /dev/null
@@ -1,2 +0,0 @@
-export const removedHelper = () => {
-};
'''


class Moves(unittest.TestCase):
    def test_moves_between_files(self):
        found = extract.names(MOVE_DIFF)
        self.assertEqual(found['src/new.ts']['moved'], [{'name': 'shared', 'from': 'src/old.ts', 'same': True},
                                                        {'name': 'reworked', 'from': 'src/old.ts', 'same': False}])
        self.assertEqual(found['src/old.ts']['removed'], ['shared', 'reworked'])

    def test_renamed_file_with_changes(self):
        switch = extract.names(MOVE_DIFF)['src/ui/Switch.tsx']
        self.assertEqual(switch['moved'], [{'name': 'Switch', 'from': 'src/ext/Old.tsx', 'same': False}])
        self.assertEqual(switch['removed'], [])

    def test_reordering_is_not_a_change(self):
        reorder = extract.names(MOVE_DIFF)['src/reorder.ts']
        self.assertEqual((reorder['added'], reorder['removed'], reorder['moved']), ([], [], []))

    def test_deleted_file_keeps_its_path(self):
        self.assertEqual(extract.names(MOVE_DIFF)['src/gone.ts']['removed'], ['removedHelper'])

    def test_draft_marks_moves(self):
        found = extract.names(MOVE_DIFF)
        files = [{'path': path, 'additions': 1, 'deletions': 1, **found[path]} for path in ('src/new.ts', 'src/ui/Switch.tsx')]
        pr = {**raw_pr(5, 'refactor/move', []), 'files': files}
        fns = {f['name']: f for f in build.functions(draft.draft({'repo': 'o/r', 'default': 'main', 'prs': [pr]}))}
        self.assertEqual(fns['shared']['moved'], {'from': 'src/old.ts', 'to': 'src/new.ts'})
        self.assertEqual(fns['reworked']['moved'], {'from': 'src/old.ts', 'to': 'src/new.ts', 'changed': True})
        self.assertTrue(fns['shared']['why'].startswith('moved ·'))
        self.assertFalse(fns['reworked']['key'])

    def test_extension_from_the_path(self):
        self.assertEqual(draft.ext_of('src/extensions/yfm/YfmTabs/plugin.ts'), 'YfmTabs')
        self.assertEqual(draft.ext_of('packages/editor/src/extensions/markdown/Bold/index.ts'), 'Bold')
        self.assertEqual(draft.ext_of('src/core/utils/dom.ts'), 'core')
        self.assertEqual(draft.ext_of('packages/ui/src/title/node.ts'), 'ui')


class Details(unittest.TestCase):
    def fn(self, data):
        return data['stacks'][0]['prs'][0]['groups'][0]['fns'][0]

    def problems(self, **fields):
        data = example()
        self.fn(data).update(fields)
        return '\n'.join(build.check(data))

    def test_limits_and_types(self):
        self.assertIn('about 501 > 500', self.problems(about='x' * 501))
        self.assertIn('without 201 > 200', self.problems(without='x' * 201))
        self.assertIn('ext 41 > 40', self.problems(ext='x' * 41))
        self.assertIn('ext is empty', self.problems(ext=' '))
        self.assertIn("type 'big'", self.problems(type='big'))
        self.assertIn('line 0', self.problems(line=0))
        self.assertIn('is not a link', self.problems(code='src/a.ts'))
        for wrong in (-1, True, '3', [{'in': 'Caller', 'pr': 0, 'url': 'https://x'}], [{'in': 'Caller', 'pr': None}]):
            with self.subTest(uses=wrong):
                self.assertIn('uses: expected a list', self.problems(uses=wrong))
        for wrong in ({'from': 'a.ts'}, 'a.ts', {'from': 'a.ts', 'to': 'b.ts', 'changed': 'yes'}):
            with self.subTest(moved=wrong):
                self.assertIn('moved', self.problems(moved=wrong))

    def test_an_unchanged_move_needs_no_why(self):
        self.assertEqual(self.problems(why='', moved={'from': 'a.ts', 'to': 'b.ts'}), '')
        self.assertIn('why is empty', self.problems(why='', moved={'from': 'a.ts', 'to': 'b.ts', 'changed': True}))

    def test_described(self):
        full = {'type': 'logic', 'ext': 'Banner', 'about': 'a', 'without': 'b', 'uses': []}
        self.assertTrue(build.described(full))
        self.assertTrue(build.described({'moved': {'from': 'a', 'to': 'b'}}))
        self.assertFalse(build.described({'moved': {'from': 'a', 'to': 'b', 'changed': True}}))
        self.assertFalse(build.described({**full, 'type': None}))
        self.assertFalse(build.described({k: v for k, v in full.items() if k != 'uses'}))

    def test_diff_link_names_the_file_by_its_hash(self):
        pr = {'url': 'https://github.com/o/r/pull/7'}
        digest = hashlib.sha256(b'src/a.ts').hexdigest()
        self.assertEqual(build.diff_link(pr, {'file': 'src/a.ts', 'line': 12}), f'https://github.com/o/r/pull/7/files#diff-{digest}R12')
        self.assertIsNone(build.diff_link(pr, {}))

    def test_markdown_carries_the_details(self):
        listing = build.markdown(example())
        self.assertIn('— Row with a switch · `std` · [UI] · logic · editor-banner-extension', listing)
        self.assertIn('    - Moved and changed: `packages/', listing)
        self.assertIn('    - The settings window that opens next to a banner.', listing)
        self.assertIn('    - It cannot go: the banner settings window', listing)
        self.assertRegex(listing, r'    - Used in: \[SettingsFields\]\(https://github\.com/[^)]+\) \(main\)')

    def test_unchanged_move_is_one_line(self):
        data = example()
        f = self.fn(data)
        f.update(why='', moved={'from': 'src/a.ts', 'to': 'src/b.ts'})
        listing = build.markdown(data)
        self.assertIn(f'  - `{f["name"]}` · moved: `src/a.ts` → `src/b.ts`\n', listing)


class Guards(unittest.TestCase):
    DIFF = '''diff --git a/src/is.ts b/src/is.ts
--- /dev/null
+++ b/src/is.ts
@@ -0,0 +1,12 @@
+export const isNode = (value: unknown): value is Node =>
+    value instanceof Node;
+export function hasTitle(attrs) {
+    return Boolean(attrs.title);
+}
+export const pick = (a, b) => a ?? b;
+export function render(view) {
+    const dom = view.dom;
+    dom.textContent = '';
+    view.update();
+    return dom;
+}
'''

    def test_type_guards_and_small_helpers(self):
        found = extract.names(self.DIFF)['src/is.ts']
        self.assertEqual(found['guards'], ['isNode', 'hasTitle'])
        self.assertEqual(found['small'], ['pick'])

    def test_draft_takes_the_type_and_the_file(self):
        found = extract.names(self.DIFF)
        pr = {**raw_pr(9, 'feat/is', []), 'files': [{'path': 'src/is.ts', 'additions': 12, 'deletions': 0, **found['src/is.ts']}]}
        fns = {f['name']: f for f in build.functions(draft.draft({'repo': 'o/r', 'default': 'main', 'prs': [pr]}))}
        self.assertEqual({name: f['type'] for name, f in fns.items()},
                         {'isNode': 'guard', 'hasTitle': 'guard', 'pick': 'util', 'render': 'logic'})
        self.assertEqual(fns['render']['file'], 'src/is.ts')


BANNER = '''import {
    SettingsDialog,
    SettingsRow,
} from './settings';
export {SettingsRow} from './settings';

// SettingsDialog of the banner
export function BannerSettings({
    block,
}: Props) {
    if (block) {
        log(1);
    } else {
        return <SettingsRow label="a" />;
    }
    return (
        <SettingsDialog title="x">
            <SettingsRow label="b" />
        </SettingsDialog>
    );
}

export const BannerPanel: FC<Props> = ({
    open,
}) => {
    const inner = () => <SettingsRow label="c" />;
    return list.SettingsRow;
};

export const headerPart = {
    create(schema) {
        return schema.create();
    },
    adopt: (node) => headerPart.create(node),
};

class View {
    renderAttrs() {
        this.update();
    }
    update() {
        this.renderAttrs();
    }
}

register(SettingsDialog);
'''


class Uses(unittest.TestCase):
    LINES = BANNER.splitlines()

    def at(self, text):
        return next(i for i, line in enumerate(self.LINES) if text in line)

    def test_the_function_around_a_line(self):
        self.assertEqual(uses.around(self.LINES, self.at('<SettingsDialog title')), 'BannerSettings')
        self.assertEqual(uses.around(self.LINES, self.at('label="a"')), 'BannerSettings')
        self.assertEqual(uses.around(self.LINES, self.at('label="c"')), 'BannerPanel')
        self.assertEqual(uses.around(self.LINES, self.at('return schema.create')), 'headerPart.create')
        self.assertEqual(uses.around(self.LINES, self.at('this.renderAttrs')), 'View.update')
        self.assertIsNone(uses.around(self.LINES, self.at('register(')))

    def test_declarations(self):
        self.assertTrue(uses.declares('export const BannerPanel: FC<Props> = ({', 'BannerPanel'))
        self.assertTrue(uses.declares('    adopt: (node) => headerPart.create(node),', 'adopt'))
        self.assertTrue(uses.declares('    renderAttrs() {', 'renderAttrs'))
        self.assertFalse(uses.declares('        log(1);', 'log'))

    def test_imports_and_comments_are_skipped(self):
        skip = uses.skipped(self.LINES)
        for text in ('import {', '    SettingsDialog,', "} from './settings';", 'export {SettingsRow}', '// SettingsDialog'):
            self.assertIn(self.at(text), skip)
        self.assertNotIn(self.at('<SettingsDialog title'), skip)

    def repo(self, files):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        git = ['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
               '-c', 'core.hooksPath=/dev/null']
        for args in (['init', '-q'], ['add', '.'], ['commit', '-q', '-m', 'x'], ['update-ref', 'refs/prmap/1', 'HEAD']):
            subprocess.run([*git, *args], check=True, capture_output=True)
        return uses.Tree(root / '.git', 'refs/prmap/1')

    def test_places_and_declaration_in_a_tree(self):
        tree = self.repo({'src/Banner.tsx': BANNER, 'src/Banner.test.tsx': 'SettingsRow();\n', 'README.md': 'SettingsRow\n',
                          'src/settings.tsx': 'export function SettingsRow() {\n    return null;\n}\n'})
        found = uses.places(tree, 'SettingsRow (rows)', {'BannerSettings': 'BannerSettings (#2)'})
        self.assertEqual(sorted(found), [('src/Banner.tsx', 'BannerPanel'), ('src/Banner.tsx', 'BannerSettings (#2)')])
        self.assertEqual(found[('src/Banner.tsx', 'BannerSettings (#2)')], self.at('label="a"') + 1)
        self.assertEqual(uses.places(tree, 'headerPart.create', {}), {('src/Banner.tsx', 'headerPart.adopt'): self.at('adopt:') + 1})
        self.assertEqual(uses.places(tree, 'renderAttrs', {}, only='src/Banner.tsx'), {('src/Banner.tsx', 'View.update'): self.at('this.renderAttrs') + 1})
        self.assertEqual(uses.declaration(tree, 'SettingsRow', ['src/settings.tsx']), {'file': 'src/settings.tsx', 'line': 1})
        self.assertEqual(uses.declaration(tree, 'View.renderAttrs'), {'file': 'src/Banner.tsx', 'line': self.at('    renderAttrs() {') + 1})
        self.assertTrue(tree.has('src/settings.tsx', 'return null;'))
        self.assertIsNone(tree.lines('src/missing.ts'))

    def test_chains_follow_the_bases(self):
        prs = {1: {'base': 'main', 'head': 'a'}, 2: {'base': 'a', 'head': 'b'}, 3: {'base': 'b', 'head': 'c'},
               9: {'base': 'main', 'head': 'z'}}
        chains = uses.chains(prs)
        self.assertEqual(chains[2], [1, 2, 3])
        self.assertEqual(chains[9], [9])


class Cli(unittest.TestCase):
    def test_example(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        res = subprocess.run([sys.executable, str(ROOT / 'prmap'), 'example', '--no-open', '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['map.artifact.html', 'map.html', 'map.md'])


if __name__ == '__main__':
    unittest.main()
