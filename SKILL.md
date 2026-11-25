---
name: pr-mindmap
description: Build an interactive mind map of a GitHub PR or a stack of PRs from its link — the essence of the stack and of each PR, the functions grouped by meaning with a ≤50-char purpose, and on a click a plain-language explanation a manager understands, how many places use the function, its plugin or extension and what happens without it, plus the risks of each function, found by one agent per PR and checked one by one in a full review report (the review-findings-report skill), each risk a link to its card of the report in a new window and a triangle in the color of its level (high, medium, low) with the number of risks on every node, folded or not; moved functions marked from → to; key/standard/unique marks, colors by kind of work, similar-function links, a review order through each PR from the helpers to the main function, search, pinch zoom, depth and density controls, filters and foldable chrome — published as an HTML artifact plus a Markdown list. Use when the user gives one or more PR or stack links and asks for a mind map, a map, an overview or a function breakdown of the PR(s) ("ммап", "построй майнд мап пр-а", "карта PR", "карта стека", "mind map this PR").
argument-hint: <PR or stack URL> [more URLs] [only this PR]
---

# PR mind map

Build the map for: $ARGUMENTS

Work unattended: never ask questions; take the safe option and say what you chose in the final report.
Write the map text in the language of the request: Russian for a request in Russian, English otherwise. Set `lang` of the data to it (`"ru"` or `"en"`): the page and the Markdown list speak that language. Code names stay as they are.

The skill folder is `~/.claude/skills/pr-mindmap/`; `prmap` in it runs every step (`prmap --help`):
- `prmap extract` — PR metadata, the stack chain and the names each diff defines (gh CLI) → `raw.json`;
- `prmap draft` — a mechanical `data.json` from `raw.json`: the structure without the meaning;
- `prmap uses` — the declaration of every function (`file`, `line`, `code`) and the places that call it (`uses`),
  across the repository at the top of its stack, tests, stories, imports and definitions aside;
- `analysis.md` — the brief of the agent that analyses one PR: `about`, `without` and `risks` of each of its
  functions, written to `<work>/analysis/<n>.json`; `prmap merge` folds them into `data.json`;
- `prmap report` — numbers the risks and writes `findings.json` and `context.md` of the report to `<work>/report/`;
  the review-findings-report skill (`~/.claude/skills/review-findings-report/`) builds the report from them;
- `prmap build` — checks `data.json` and builds the map from `template.html`: `map.html` (a complete file to open
  from disk), `map.artifact.html` (the same page in the form the Artifact tool publishes) and `map.md`;
  the docstring of `build.py` is the data schema;
- `template.html` — the page: a tree that grows to both sides of the root, search, zoom, depth and density controls,
  filters, inspector, minimap, and five skins the reader picks in the bar (GitHub by default); do not edit it for one map;
- `example/banner.json` — a complete real map (15 PRs, 166 functions) to copy the style and the level of detail from.

## 1. Collect

Pick a work folder: the session scratchpad if there is one, otherwise `/tmp/pr-mindmap-<first PR number>`.

```bash
~/.claude/skills/pr-mindmap/prmap extract <PR and stack URLs> --out <work>/raw.json
~/.claude/skills/pr-mindmap/prmap draft <work>/raw.json --out <work>/data.json
```

A stack link (`github.com/<owner>/<repo>/stack/<n>`) brings the PRs of that GitHub stack. A stacked PR brings its whole chain (PRs below down to the default branch and open PRs above). Add `--no-chain`
when the user says "only this PR" or lists exact PRs that do not form one chain.

`raw.json` lists per PR: title, body, base/head, GitHub stack, commits and files; each file has `added` (names its added lines
define), `exported`, `touched` (existing definitions whose body changed), `types`, `removed` (deleted definitions) and
`moved` (added names that come from another file or from the old path of a renamed file, `same: true` when the body
matches line by line).
The names are a starting point, not the answer: open the diff (`gh pr diff <n> -R <repo>`) of every PR and read it.
Drop false positives (hooks called inside components, local variables, CSS class constants) and add what the regex
missed (methods of object literals; for changed behavior of an existing function say what changed in `why`).

The draft `data.json` is valid and already has every PR with its number, link and branch, so keep its skeleton.
Everything that carries meaning in it is a placeholder to rewrite: stacks named after branches, groups named after
folders, `why` holding a file name, colors standing for packages, `key` guessed from the PR text, similar groups
found by name endings.

## 2. Model the map

Levels: root → stacks → PRs → groups → functions. Read `example/banner.json` before rewriting the draft.

- **Root**: `title` of the page is a 2–4 word name ("Banner stack map"); `root.essence` ≤150 chars.
- **Stacks**: GitHub stacks or runs of the chain that build one feature (2–4 PRs each); a PR on its own is a stack of one.
  `essence` ≤150 chars, `gh` names the stack ("stack 1491", or "no stack"); with "stack N" the card links to the
  GitHub stack, a card of one PR links to the PR.
- **A lone PR**: make the branches from its areas instead — stacks are areas of the change (packages or features), and
  each area has 1–4 PR-level cards for its parts, all with the same `n` and `url`. A map with one branch shows no structure.
- **PR**: `title` short and in the map language, `essence` ≤200 chars: what the PR gives the user or the code.
  `state` (open, draft, merged, closed) comes from the draft and sets the PR icon; keep it.
- **Groups**: 2–5 per PR by meaning ("Commands", "Schema", "Settings dialog"), not by file.
- **Functions**: every function, component, class or method that matters to a reviewer; skip trivial constants.
  - `why` ≤50 chars, what it is for, not how it works.
  - `key: true` for the ones the PR is built around (entry points, main commands, non-obvious logic): about a quarter.
  - `kind`: `"s"` standard — a usual pattern of the framework (specs, parser/serializer, plugin factory, getters,
    plain UI); `"u"` unique — logic specific to this project.
  - Names are unique across the map; when two PRs touch the same name, add a short suffix: `SettingsFields (alignment)`.
  - A method is named `Owner.method` (`WHeaderNodeView.renderAttrs`, `headerPart.create`): the card shows it as a
    method by that dot.
  - `type`: `"logic"` does real work, `"guard"` is a type guard or a yes/no check of a value, `"util"` is a small
    helper of a few lines. The draft guesses it from the signature and the size of the body.
  - `ext` ≤40 chars: the plugin or extension the function belongs to, by its name in the code (`YfmTabs`, `Mermaid`);
    code outside plugins and extensions gets its package or module (`core`). The draft guesses it from the path.
  - `file`, `line`, `code` and `uses` come from `prmap uses` in step 3; `about`, `without` and `risks` from the
    agents of step 4. `example/banner.json` has all of them on `SettingsDialog`, `SettingsRow` and `SettingsSwitch`
    of #1475.
  - `moved` (`{"from", "to"}`): the draft sets it when the PR deletes a definition in one file and adds it in another,
    with `"changed": true` when the body differs; check each one in the diff. An unchanged move is only a move: no
    `why`, `about`, `without` or `ext`; the card shows the old and the new path, as GitHub shows a renamed file. A
    changed one is described as usual, and `about` says what changed. A file renamed without changes shows no
    names: its functions stay out of the map.
- **Review order**: the page goes through the functions of one PR with the R button, from the ones that need nothing
  in the PR to the main ones; a step shows `why`, its note and the map functions it relies on and is needed for.
  A function needs the map functions that name it in their `uses`, so a wrong link is fixed in `uses`.
  - `main: true` on the 1–2 functions the PR is built around, from the key ones. Without it the builder takes the
    key functions that no function of the PR needs.
  - `path` of a PR card, `[{"fn", "note"}]`, is written in step 6: every function of the card but the unchanged
    moves, once. Start from the order that `prmap build` writes to `map.md` and move a step only when the code
    reads better otherwise. `note` ≤150 chars tells a reviewer what to check on that step, in the map language,
    without repeating `why`.
- **Colors** (`cats`, 3–10, legend order): kinds of work across the whole map (Markdown, schema, commands, cursor and
  keys, guards, text input, DOM, UI, upload, model…). Follow **Remember topic colors** below. `desc` explains the
  category in one sentence. Every function gets exactly one category via `cat`.
- **Similar** (`sims`): groups of 2+ functions that do the same job for different parts (the `*Values` of each part,
  the `*ParserSpecs`, the Backspace/Delete selectors…). Label says what they share. Only real look-alikes.

### Remember topic colors

Read `~/.local/state/pr-mindmap/topic-colors.json` before choosing the map's categories. It is a local JSON object
keyed by stable category IDs, with entries of the form `"md": {"name": "Markdown", "colors": ["#0b8276", "#3ccfbf"]}`.
Create the directory and start with an empty JSON object if the file is missing.

- Match topics by meaning. Reuse the saved ID and both colors when a topic recurs, even if the legend order or
  the map language changes. Translate the map's `name` and `desc` as needed.
- For a new topic, choose a stable ID and a distinct pair of readable `#RRGGBB` colors, light skin first and dark
  skin second. Merge the new entry into the latest registry, preserving all previous assignments.
- Copy each category's `colors` pair into its entry in `data.json`. The builder embeds both colors in the HTML
  and the published Artifact. Both outputs render independently of the local registry.

## 3. Find the code

For the final list of functions:

```bash
~/.claude/skills/pr-mindmap/prmap uses <work>/data.json
```

`uses` lists the places that call a function across the repository at the top of its stack, each with the PR that
added it or `null` for the default branch; `code` links a function the default branch has already. A key function with no places, or a common name with 30+, is likely a miscount: check it with
`git --git-dir ~/.cache/pr-mindmap/<owner>__<repo> grep -w <name> refs/prmap/<PR number>` and fix the list.

## 4. Analyse each PR

Start one agent per PR number with the Agent tool, `subagent_type: "general-purpose"` and `run_in_background: false`,
all in one message so they work at the same time. The prompt of each:
`Follow ~/.claude/skills/pr-mindmap/analysis.md for PR <n> of <owner>/<repo>; the work folder is <work>.`
When they are done:

```bash
~/.claude/skills/pr-mindmap/prmap merge <work>/data.json
```

It folds `<work>/analysis/<n>.json` into the data and lists what it left out: a PR without a file gets a new agent
once; a missing or unknown function is fixed in that file by hand, and the merge runs again.

## 5. Build the report

```bash
~/.claude/skills/pr-mindmap/prmap report <work>/data.json
```

It numbers the risks, writes `<work>/report/findings.json` and `context.md` and sets `report` of the data: in
`map.html` each risk links its card of the report, and `prmap build` takes the checked level of each risk from its card. Then build the report by steps 2–4 of
`~/.claude/skills/review-findings-report/SKILL.md` with the folder `<work>/report`: an agent per finding, `build.py`,
the shots. A map without risks skips this step.

## 6. Build and check

```bash
~/.claude/skills/pr-mindmap/prmap build <work>/data.json
```

It writes `map.html`, `map.artifact.html` and `map.md` next to the data. Fix every error it prints (lengths, unknown
colors, duplicate names). Then write `main` and `path` from the «Review order» of each PR in `map.md` and build
again until it prints `ok` with `details N/N`, `risks N/N`, `report R/R` and `paths N/N`: every function described
and analysed, every risk in the report, every PR with its path. A warning about a color without
functions means the color should go; a warning about a step that comes before a function it needs means the step
moves or `uses` is wrong.
If Google Chrome is installed, take one look:
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars --user-data-dir=<work>/chrome --window-size=1600,1000 --virtual-time-budget=6000 --screenshot=<work>/map.png file://<work>/map.html`
and read the PNG once. Fix only what is visibly broken; no second look.

## 7. Publish and report

Publish `map.artifact.html` as an Artifact (icon `map`, description: one sentence naming the PRs); `map.html` is the
standalone copy for opening from disk, and its links to the report lead to the folder `report` next to it. Copy
`map.html`, `map.md` and `report/` to the folder the user named, if any; otherwise leave them in the work folder.

Final report, short, in the user's language:
- the artifact link and the paths of `map.html`, `map.md`, `data.json` and `report/index.html`;
- the PRs covered and how they were grouped into stacks;
- counts: PRs, functions, key, main, standard/unique, moved, risks by level, colors, similarity groups, and the
  summary line of the report;
- anything chosen without asking (chain included or not, a lone PR split into areas).
