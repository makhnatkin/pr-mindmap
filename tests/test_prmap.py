#!/usr/bin/env python3
"""Tests of the builder, the extractor and the draft. Run: python3 -m unittest discover -s tests -v

The browser test needs Google Chrome or Chromium and is skipped without one; the syntax test needs node.
"""
import copy
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
        self.assertEqual(build.ref_of(st('без stack', 7)), {'kind': 'pr', 'n': 7, 'url': 'https://github.com/o/r/pull/7'})
        self.assertIsNone(build.ref_of(st('#1–#2', 1, 2)))
        self.assertIn('(https://github.com/o/r/stack/', build.markdown(example()))

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
        self.assertTrue(next(f for f in fns if f['name'] == 'titleNode (#2)')['why'].startswith('изменена'))

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


class Cli(unittest.TestCase):
    def test_example(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        res = subprocess.run([sys.executable, str(ROOT / 'prmap'), 'example', '--no-open', '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['map.artifact.html', 'map.html', 'map.md'])


if __name__ == '__main__':
    unittest.main()
