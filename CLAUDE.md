# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Overview

Donovan's published Icarus mods. Each mod is hand-maintained source plus a built
artifact committed at the repo root:

```text
<Mod>/<Mod>.EXMOD        source: the diff manifest
<Mod>/**/*.uasset|.uexp  source: prebuilt UE assets, under a <Mod>/ wrapper dir
<Mod>.EXMODZ            built artifact (zip of the two, published)
<Mod>.md                readme, linked from modinfo.json
modinfo.json            catalog entry consumed by the Firestore mod database
```

`.uasset`/`.uexp` files are compiled Unreal assets. They can only be produced in
the Unreal Editor — treat them as opaque binaries here, never hand-edit them.

## Do these mods go stale when Icarus updates?

**Table patches: no.** An `.EXMOD` is a *diff*, rebased onto the game's current
`data.pak` every time a mod manager compiles it. That is the whole difference
from a prebuilt `.pak`, which is frozen against whatever `data.pak` existed when
it was built. The `week` field in `.EXMOD`/`modinfo.json` is metadata, not a
compatibility gate — `modinfo.json` declares `"compatibility": "all"`.

**Bundled assets: yes, potentially.** An asset is a whole-file override, frozen
at build time. It does not rebase. If the game moves or renames the asset it
overrides, the override silently stops applying — the mod still installs, still
deploys, and does nothing.

Two other silent failures are possible on the table side: a row this repo
patches gets renamed or removed upstream, or the base game's own value catches
up to the patch, making it a no-op.

None of these announce themselves. That is what the drift check is for.

## Drift check

Run after a game update, or any time you want to know whether these mods still
do what their readmes claim:

```bash
./tools/check-mods.py
```

Requires the `unrealpak` CLI ([go-unrealpak](https://github.com/DonovanMods/go-unrealpak));
pass `--unrealpak <path>` if it is not on `PATH`, and `--game-dir` if Icarus is
not at the default Steam library location. `--skip-assets` skips the pakchunk
index scan, which is the slow part. Exit status is non-zero if any mod is broken.

Verdicts:

| Verdict | Meaning | Action |
| --- | --- | --- |
| `ok` | patch or asset resolves against the current game | none |
| `no-op` | the base game's value already matches the patch | consider dropping the patch — it does nothing |
| `?` | row or field is not in the base | fine for a content-adding mod; otherwise it was renamed upstream |
| `FAIL` | table or asset is gone from the base game | the mod is broken and needs updating |

`no-op` and `?` are judgement calls and do not fail the run. Only `FAIL` does.

## If artifacts ever need rebuilding

A `.EXMODZ` is a plain zip: `Extracted Mods/<Mod>.EXMOD` plus the `<Mod>/` asset
tree verbatim. Two rules matter and are easy to get wrong:

- **`.EXMOD` carries fields most parsers drop** — `week`, `fileName`,
  `readmeURL`, `imageURL`, `Level2`. Preserve them. Do not round-trip the
  manifest through a tool that only understands `name`/`author`/`version`/
  `description`/`Rows`.
- **The `<Mod>/` wrapper directory is stripped at compile time.** In the
  `.EXMODZ` an asset is `MegaPoints/data/Character/X.uasset`; in the compiled
  pak it must land at `Icarus/Content/data/Character/X.uasset`, matching the
  base game's own path. Carrying the wrapper through puts every asset one
  directory too deep, where the game ignores it. (This was a real shipped bug in
  a mod manager — DonovanMods/linux-mod-manager#237.)

`version` is semantic and changes only when a mod's content changes. `week`
records which game build an artifact was built against.

## Conventions

- Standard `git`, not `yadm` — this is an ordinary repo.
- `modinfo.json` is the published catalog entry; update it when a mod's version,
  description, or readme URL changes.
