# Working on the add-on from any computer

The repository root IS the add-on: Blender loads it straight from a clone, so every computer
works the same way.

## Set up a computer (once)

1. Install Blender 5.2 LTS and/or 5.3 and git.
2. Clone the repository:

   ```
   git clone https://github.com/Aasmundivarjord/Blender-Conveyor-Add-On.git conveyor_system
   ```

3. Let Blender load the clone as the installed extension: a link named `conveyor_system` in
   the extensions folder of each Blender version, pointing at the clone (uninstall a zip-installed
   copy first).

   - macOS: `ln -s ~/code/conveyor_system "$HOME/Library/Application Support/Blender/5.3/extensions/user_default/conveyor_system"`
   - Linux: `ln -s ~/code/conveyor_system ~/.config/blender/5.3/extensions/user_default/conveyor_system`
   - Windows (Command Prompt): `mklink /J "%APPDATA%\Blender Foundation\Blender\5.3\extensions\user_default\conveyor_system" C:\code\conveyor_system`

4. Start Blender: Edit > Preferences > Add-ons shows "Path-Driven Conveyor System". After
   editing code, disable and enable it there (or restart Blender).

## Every day

- `git pull` before you start, `git push` when you stop: the other computer picks up from there.
- Small, separate commits; run the tests before committing (below).

## Tests

- Pure Python, no Blender (from the repository root): `python3 -m unittest discover -s tests -p "test_*.py"`
- In Blender, headless: `tests/headless/run_all.sh` runs every suite and prints one line each
  (its header says how to point it at a scratch config so your own Blender settings are never
  touched).
- GUI smoke: see the header of `tests/gui/smoke.py`.

## Node libraries

`geonodes/library/conveyor_nodes-<major>.<minor>.blend` are the pre-built node trees, one per
Blender series. After changing a builder, rebuild them in BOTH series and commit them
(`git add -f`, `*.blend` is otherwise ignored):

```
blender -b --factory-startup --python tools/build_tree_library.py
```

## Release

1. Bump `version` in `blender_manifest.toml`; tests green on 5.2 and 5.3.
2. Tag it (`git tag v2.x.y`), then build the zip from the clean tagged tree:
   `blender --command extension build --source-dir . --output-dir ../dist`
3. `blender --command extension validate ../dist/conveyor_system-2.x.y.zip`, install the zip once
   yourself, then upload it on extensions.blender.org.
