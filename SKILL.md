---
name: pr-mindmap
description: Build an interactive mind map of a GitHub PR or a stack of PRs from its link — the essence of the stack and of each PR, the functions grouped by meaning with a ≤50-char purpose, key/standard/unique marks, colors by kind of work, similar-function links, search, pinch zoom, depth and density controls, filters and foldable chrome — published as an HTML artifact plus a Markdown list. Use when the user gives one or more PR or stack links and asks for a mind map, a map, an overview or a function breakdown of the PR(s) ("ммап", "построй майнд мап пр-а", "карта PR", "карта стека", "mind map this PR").
argument-hint: <PR or stack URL> [more URLs] [only this PR]
context: fork
agent: general-purpose
---

# PR mind map

Build the map for: $ARGUMENTS

Work unattended: never ask questions; take the safe option and say what you chose in the final report.
Write the map text in the user's language (Russian unless the request is in another language); code names stay as they are.

The skill folder is `~/.claude/skills/pr-mindmap/`; `prmap` in it runs every step (`prmap --help`):
- `prmap extract` — PR metadata, the stack chain and the names each diff defines (gh CLI) → `raw.json`;
- `prmap draft` — a mechanical `data.json` from `raw.json`: the structure without the meaning;
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
define), `exported`, `touched` (existing definitions whose body changed) and `types`.
The names are a starting point, not the answer: open the diff (`gh pr diff <n> -R <repo>`) of every PR and read it.
Drop false positives (hooks called inside components, local variables, CSS class constants) and add what the regex
missed (methods of object literals; for changed behavior of an existing function say what changed in `why`).

The draft `data.json` is valid and already has every PR with its number, link and branch, so keep its skeleton.
Everything that carries meaning in it is a placeholder to rewrite: stacks named after branches, groups named after
folders, `why` holding a file name, colors standing for packages, `key` guessed from the PR text, similar groups
found by name endings.

## 2. Model the map

Levels: root → stacks → PRs → groups → functions. Read `example/banner.json` before rewriting the draft.

- **Root**: `title` of the page is a 2–4 word name ("Карта баннер-стека"); `root.essence` ≤150 chars.
- **Stacks**: GitHub stacks or runs of the chain that build one feature (2–4 PRs each); a PR on its own is a stack of one.
  `essence` ≤150 chars, `gh` names the stack ("stack 1491", or "без stack"); with "stack N" the card links to the
  GitHub stack, a card of one PR links to the PR.
- **A lone PR**: make the branches from its areas instead — stacks are areas of the change (packages or features), and
  each area has 1–4 PR-level cards for its parts, all with the same `n` and `url`. A map with one branch shows no structure.
- **PR**: `title` short and in the map language, `essence` ≤200 chars: what the PR gives the user or the code.
  `state` (open, draft, merged, closed) comes from the draft and sets the PR icon; keep it.
- **Groups**: 2–5 per PR by meaning ("Команды", "Схема", "Окно настроек"), not by file.
- **Functions**: every function, component, class or method that matters to a reviewer; skip trivial constants.
  - `why` ≤50 chars, what it is for, not how it works.
  - `key: true` for the ones the PR is built around (entry points, main commands, non-obvious logic): about a quarter.
  - `kind`: `"s"` standard — a usual pattern of the framework (specs, parser/serializer, plugin factory, getters,
    plain UI); `"u"` unique — logic specific to this project.
  - Names are unique across the map; when two PRs touch the same name, add a short suffix: `SettingsFields (alignment)`.
- **Colors** (`cats`, 3–10, legend order): kinds of work across the whole map (Markdown, schema, commands, cursor and
  keys, guards, text input, DOM, UI, upload, model…). `desc` explains the color in one sentence:
  "Функции по работе с …". Every function gets exactly one color.
- **Similar** (`sims`): groups of 2+ functions that do the same job for different parts (the `*Values` of each part,
  the `*ParserSpecs`, the Backspace/Delete selectors…). Label says what they share. Only real look-alikes.

## 3. Build and check

```bash
~/.claude/skills/pr-mindmap/prmap build <work>/data.json
```

It writes `map.html`, `map.artifact.html` and `map.md` next to the data. Fix every error it prints (lengths, unknown
colors, duplicate names) and build again until it prints `ok`; a warning about a color without functions means the
color should go.
If Google Chrome is installed, take one look:
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars --user-data-dir=<work>/chrome --window-size=1600,1000 --virtual-time-budget=6000 --screenshot=<work>/map.png file://<work>/map.html`
and read the PNG once. Fix only what is visibly broken; no second look.

## 4. Publish and report

Publish `map.artifact.html` as an Artifact (icon `map`, description: one sentence naming the PRs); `map.html` is the
standalone copy for opening from disk. Copy `map.html` and `map.md` to the folder the user named, if any; otherwise
leave them in the work folder.

Final report, short, in the user's language:
- the artifact link and the paths of `map.html`, `map.md`, `data.json`;
- the PRs covered and how they were grouped into stacks;
- counts: PRs, functions, key, standard/unique, colors, similarity groups;
- anything chosen without asking (chain included or not, a lone PR split into areas).
