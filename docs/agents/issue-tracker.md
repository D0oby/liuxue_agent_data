# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues in `D0oby/liuxue_agent_data`.
Use the `gh` CLI for all operations.

When commands run from this directory, `gh` can infer the repo from
`git remote -v`. Use the HTTPS remote because SSH pushes may be blocked in
managed execution environments:

```text
https://github.com/D0oby/liuxue_agent_data.git
```

## Conventions

- Create an issue: `gh issue create --title "..." --body "..."`
- Read an issue: `gh issue view <number> --comments`
- List issues: `gh issue list --state open --json number,title,body,labels,comments`
- Comment on an issue: `gh issue comment <number> --body "..."`
- Apply or remove labels: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- Close an issue: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

PRs as a request surface: no.

Do not pull external PRs into the Matt skills triage queue unless this file is
explicitly changed later.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
