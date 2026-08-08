#!/usr/bin/env python3
"""Report whether each mod in this repo still does what it claims, against the
installed game's CURRENT data.

An .EXMOD is a diff, rebased onto the live data.pak every time a mod manager
compiles it, so table patches do not go stale the way a prebuilt pak does.
Two things can still rot silently, and this checks both:

  * a table patch whose row was renamed or removed, or whose value the base
    game has since caught up to (the patch becomes a no-op)
  * a bundled asset whose base-game counterpart moved or was renamed. Assets
    are whole-file overrides frozen at build time - they do NOT rebase - so a
    moved target means the override silently stops applying.

Requires the `unrealpak` CLI (github.com/DonovanMods/go-unrealpak) on PATH or
named by --unrealpak.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_GAME_DIR = "/data/SteamLibrary/steamapps/common/Icarus"

# Verdicts. Only FAIL sets a non-zero exit; NOOP is reported loudly but is a
# judgement call for the author (the base game caught up), not breakage.
OK, NOOP, FAIL = "ok", "no-op", "FAIL"


def run_unrealpak(binary, *args):
    proc = subprocess.run([binary, *args], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode().strip() or f"unrealpak {args[0]} failed")
    return proc.stdout


def base_table_paths(binary, data_pak):
    doc = json.loads(run_unrealpak(binary, "list", "--json", data_pak))
    return {f["path"] for f in doc["files"]}


def base_asset_paths(binary, paks_dir):
    """Every entry path across the game's pakchunks, ASCII-lowercased.

    Lowercased because UE virtual paths are case-insensitive and real mods
    vary the casing (the base game ships `Data/Character/...` while published
    working mods override it as `data/Character/...`).
    """
    paths = set()
    for pak in sorted(Path(paks_dir).glob("*.pak")):
        doc = json.loads(run_unrealpak(binary, "list", "--json", str(pak)))
        paths.update(f["path"].lower() for f in doc["files"])
    return paths


def read_table(binary, data_pak, entry):
    return json.loads(run_unrealpak(binary, "cat", data_pak, entry))


def check_tables(binary, data_pak, base_paths, manifest, out):
    """Resolve each row's CurrentFile and compare its fields to the live base."""
    worst = OK
    rows = [r for r in manifest.get("Rows", []) if r.get("CurrentFile") != "EndOfMod"]
    if not rows:
        out.append("    no table rows - asset-only mod")
        return worst

    for row in rows:
        current_file = row["CurrentFile"]
        # The .EXMOD flattens the mount-relative path, replacing every "/"
        # with "-"; no real base table path contains a hyphen, so reversing it
        # is unambiguous.
        entry = current_file.replace("-", "/")
        if entry not in base_paths:
            out.append(f"    {FAIL} {current_file}: no longer present in the base game")
            worst = FAIL
            continue

        doc = read_table(binary, data_pak, entry)
        by_name = {r.get("Name"): r for r in doc.get("Rows", [])}
        for item in row.get("File_Items", []):
            name = item["Name"]
            base_row = by_name.get(name)
            if base_row is None:
                # Not necessarily broken: a content-adding mod introduces rows
                # the base game does not have. But for a mod that means to
                # PATCH, a vanished row is silent breakage, so say so.
                out.append(f"    ?    {entry} :: {name}: not in base (new row, or renamed upstream)")
                continue
            for field, want in item.items():
                if field == "Name":
                    continue
                if field not in base_row:
                    out.append(f"    ?    {entry} :: {name}.{field}: field absent in base (added, or a typo)")
                elif base_row[field] == want:
                    out.append(f"    {NOOP} {entry} :: {name}.{field}: base already matches - patch does nothing")
                    if worst == OK:
                        worst = NOOP
    return worst


def check_assets(binary, mod_dir, asset_paths, out):
    """Confirm each bundled asset still has a base-game counterpart.

    The mod's own directory is the wrapper that gets stripped at compile time,
    so the path relative to it is the Content-relative path the asset must
    occupy to override the base file.
    """
    worst = OK
    assets = sorted(
        p for p in mod_dir.rglob("*")
        if p.suffix.lower() in (".uasset", ".uexp")
    )
    for asset in assets:
        rel = asset.relative_to(mod_dir).as_posix()
        if rel.lower() in asset_paths:
            out.append(f"    {OK}   {rel}")
        else:
            out.append(f"    {FAIL} {rel}: no base-game asset at this path - override does nothing")
            worst = FAIL
    return worst


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game-dir", default=os.environ.get("ICARUS_DIR", DEFAULT_GAME_DIR),
                    help="Icarus install root (default: $ICARUS_DIR or the Steam library path)")
    ap.add_argument("--unrealpak", default="unrealpak", help="path to the unrealpak binary")
    ap.add_argument("--skip-assets", action="store_true",
                    help="skip the asset check, which reads every pakchunk index")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent),
                    help="mods repo root (default: this script's parent)")
    args = ap.parse_args()

    game = Path(args.game_dir)
    data_pak = game / "Icarus/Content/Data/data.pak"
    paks_dir = game / "Icarus/Content/Paks"
    version_file = game / "Icarus/Config/version.json"

    if not data_pak.is_file():
        sys.exit(f"no data.pak at {data_pak} - pass --game-dir")

    try:
        run_unrealpak(args.unrealpak, "info", str(data_pak))
    except (RuntimeError, FileNotFoundError) as err:
        sys.exit(f"unrealpak unusable ({err}) - install github.com/DonovanMods/go-unrealpak "
                 f"or pass --unrealpak")

    if version_file.is_file():
        v = json.loads(version_file.read_text()).get("Version", {})
        print(f"game build: {v.get('Major')}.{v.get('Minor')}.{v.get('Patch')}.{v.get('Changelist')}")

    base_paths = base_table_paths(args.unrealpak, str(data_pak))
    asset_paths = set()
    if not args.skip_assets:
        print(f"indexing base assets from {paks_dir} ...", flush=True)
        asset_paths = base_asset_paths(args.unrealpak, str(paks_dir))
        print(f"  {len(asset_paths)} base entries indexed")

    repo = Path(args.repo)
    manifests = sorted(repo.glob("*/*.EXMOD"))
    if not manifests:
        sys.exit(f"no <Mod>/<Mod>.EXMOD found under {repo}")

    failures = []
    for manifest_path in manifests:
        mod_dir = manifest_path.parent
        manifest = json.loads(manifest_path.read_text())
        out = []
        print(f"\n=== {mod_dir.name} (declares week {manifest.get('week')!r}, "
              f"version {manifest.get('version')!r})")

        worst = check_tables(args.unrealpak, str(data_pak), base_paths, manifest, out)
        if not args.skip_assets:
            asset_worst = check_assets(args.unrealpak, mod_dir, asset_paths, out)
            if asset_worst == FAIL:
                worst = FAIL

        for line in out:
            print(line)
        if worst == FAIL:
            failures.append(mod_dir.name)
        elif worst == OK:
            print("    all patches and assets resolve against the current game")

    print()
    if failures:
        print(f"BROKEN: {', '.join(failures)}")
        return 1
    print("all mods resolve against the current game")
    return 0


if __name__ == "__main__":
    sys.exit(main())
