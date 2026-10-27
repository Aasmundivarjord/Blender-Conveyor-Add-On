#!/bin/sh
# Runs every headless Blender suite in this folder and prints one line per suite.
# The suites import the INSTALLED add-on (bl_ext.user_default.conveyor_system). To run them
# against dev/ without touching the install, point Blender at a scratch extensions folder whose
# user_default/conveyor_system is a symlink to dev/ (and at a scratch config folder):
#   BLENDER_USER_EXTENSIONS=/path/ext BLENDER_USER_CONFIG=/path/config ./run_all.sh
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
cd "$(dirname "$0")" || exit 1
# Every skipped case is listed under its suite ("SKIP: <what>: <why>"; SUITE_PLAN rule 9).
run() {  # label, then the suite (env set by the caller)
  printf '%s: ' "$1"
  out=$("$BLENDER" -b --python "$2" 2>&1)
  printf '%s\n' "$out" | grep -E "^RESULT|Traceback" | head -2 | tr '\n' ' '
  echo
  printf '%s\n' "$out" | grep -E "^SKIP" | sed 's/^/    /'
}
for t in test_*.py; do
  run "$t" "$t"
done
# test_round6_w2 covers one branch per run: again with the sandbox's Racks enabled (the joint suite's tag)
CONVEYOR_TEST_WITH_RACKS=1 run "test_round6_w2.py (Racks enabled)" test_round6_w2.py
