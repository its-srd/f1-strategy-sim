#!/bin/zsh
# Build the website and publish it to the gh-pages branch, which GitHub Pages
# serves at https://<user>.github.io/<repo>/. Only the built site (code,
# fitted parameters, docs) is published; no raw F1 data.
#   ./scripts/publish_site.sh
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/node/bin:$PATH"
(cd web && npm run build >/dev/null)
rm -rf .site && git worktree prune
if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git fetch -q origin gh-pages
  git worktree add -q .site -B gh-pages origin/gh-pages
else
  git worktree add -q --detach .site
  (cd .site && git checkout -q --orphan gh-pages && git rm -rqf .)
fi
find .site -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R web/dist/. .site/
touch .site/.nojekyll                       # serve files as-is
cd .site
git add -A
if git diff --cached --quiet; then echo "site unchanged"; else
  git commit -qm "Publish site $(date -u +%Y-%m-%dT%H:%MZ)" && git push -q origin gh-pages && echo "site published"
fi
cd .. && git worktree remove --force .site
