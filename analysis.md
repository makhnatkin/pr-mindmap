# Analysis of one PR for the map

The task names the PR number `<n>`, the repository `<owner>/<repo>` and the work folder `<work>`.
The result is the analysis of each function of the PR on the map: what it is for, what the product loses without it
and its risks. Each risk becomes a finding of the report of the map, checked by its own agent.

## Input

- `<work>/data.json`: the functions of the PR are in the PR cards with `"n": <n>` (a lone PR may have several
  cards). Each has `why`, `file` and `line` (its declaration at the head of the PR) and `uses` (the places that call
  it). `lang` is the language of the map.
- The PR text: `gh pr view <n> -R <owner>/<repo>`; the diff: `gh pr diff <n> -R <owner>/<repo>`.
- A whole file at the head of the PR: `git --git-dir ~/.cache/pr-mindmap/<owner>__<repo> show refs/prmap/<n>:<path>`;
  `refs/prmap/main` is the default branch.

## Rules

- Write only the result file. Send nothing to GitHub or other services; install, build and test nothing.
- Every statement comes from the diff, the code or the PR text. What the code does not show is not written.
- The text is in the language of the map. `about` and `without` are for a reader who does not write code, such as a
  manager: what the user or the product gets, in short sentences, with no code names and no framework terms; a term
  that cannot go is explained in the same sentence. `risks` are for a reviewer: code names go in backticks.

## Result

Write `<work>/analysis/<n>.json` and answer with one line: the PR number and the number of functions written.

```json
{"pr": 1475, "fns": {
  "SettingsDialog": {
    "about": "≤ 500 chars",
    "without": "≤ 200 chars",
    "risks": [{
      "title": "≤ 200 chars",
      "level": "high | mid | low",
      "what": "what goes wrong and when",
      "why": "the cause in the code",
      "suggestion": "how to fix it",
      "at": "path/from/the/repository/root.tsx:42"
    }]
  }
}}
```

Every function of the PR gets an entry, except an unchanged move (`moved` without `"changed": true`).

- `about`: what the function is for and where the user meets its result. The card shows it right under `why`, so it
  does not repeat `why`. A changed move says what changed.
- `without`: one sentence that stands alone: whether the product can do without the function, then the risk. In
  Russian it opens with «Можно без неё, но …», «Без неё нельзя: …» or «Отчасти: …»; in English with "It can go,
  but …", "It cannot go: …" or "Partly: …".
- `risks`: 0–3 things a reviewer checks: an edge case, an input the code does not expect, an order of events, a
  state that is lost or left behind. An empty list means the code has nothing worth a look.
  - `title`: the risk in one line; the card of the function shows it as the link to the card of the report.
  - `level`: what the risk costs, by the worst case the code allows. `high`: data is lost or broken, the page
    fails, or the main scenario of the PR does not work. `mid`: a visible defect in a less common case, or a
    workaround the user has to know. `low`: a rare edge case, a defect only a developer sees, or a gap in the
    docs or tests. The map colors the risk by it, red, orange or yellow, and counts the risks of each level on
    every node; the report checks it and the map takes the checked level.
  - `what`: what goes wrong and when, in 1–2 sentences; `why`: the code that causes it; `suggestion`: the fix in 1–2
    sentences.
  - `at`: the line at the head of the PR where it happens, in a file the PR changes; leave it out when there is no
    such line.

