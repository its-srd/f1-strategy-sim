#!/bin/zsh
# Bring everything up to date after a race weekend:
#   new races and qualifying -> combined tables -> refit -> docs -> website.
# Each step only adds what is missing, so it is safe to run any time.
#   ./scripts/update.sh
set -e
set -o pipefail      # a failing step inside a pipe stops the script too
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/node/bin:$PATH"
echo "1/5 races";        .venv/bin/python scripts/export_races.py | tail -3
echo "2/5 qualifying";   .venv/bin/python scripts/export_quali.py | tail -1
echo "   long runs";      .venv/bin/python scripts/export_practice.py | tail -1
echo "3/5 tables";       .venv/bin/python scripts/build_processed.py | head -2
echo "4/5 model";        .venv/bin/python model/fit_all.py 2>&1 | grep -E "exported|Error" ; .venv/bin/python model/practice_wear.py | tail -1; .venv/bin/python model/report.py
# Rolling backtest: the newest races refitted on earlier data only, which
# also measures this season's race-pace spread (I5).
SEASON=$(.venv/bin/python -c "import json; print(json.load(open('data/params/meta.json'))['target_season'])")
echo "   as-of fits";     { .venv/bin/python model/backtest.py fit "$SEASON" 2>&1 | grep -cE "fitted in" || true; }; .venv/bin/python model/calibrate_pace.py | grep "season form now"
echo "5/5 website";      (cd web && npm run build 2>&1 | grep -E "built|error")
.venv/bin/python -c "import json; m=json.load(open('data/params/meta.json')); print('model now learned through', m['data_through'], m['last_race'])"
