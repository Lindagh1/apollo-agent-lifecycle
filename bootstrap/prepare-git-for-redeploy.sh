#!/usr/bin/env bash
set -euo pipefail

COMMIT=false
PUSH=false

for ARG in "$@"; do
  case "$ARG" in
    --commit) COMMIT=true ;;
    --push) PUSH=true ;;
    *) echo "Unknown argument: $ARG"; exit 1 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "==> Repo: $ROOT"
echo "==> Branch: $(git branch --show-current)"

mkdir -p /tmp/apollo-git-cleanup

echo
echo "==> 1. Update .gitignore"

touch .gitignore

add_ignore() {
  grep -qxF "$1" .gitignore || echo "$1" >> .gitignore
}

add_ignore "__pycache__/"
add_ignore "*.pyc"
add_ignore ".venv/"
add_ignore "venv/"
add_ignore "node_modules/"
add_ignore "dist/"
add_ignore "build/"
add_ignore ".DS_Store"
add_ignore ".vscode/"
add_ignore ".idea/"
add_ignore "*.bak"
add_ignore "*.bak.*"
add_ignore "*.backup"
add_ignore "*.tmp"
add_ignore "*~"
add_ignore "exports/"
add_ignore "*.tgz"
add_ignore "*.tar.gz"
add_ignore ".env"
add_ignore "*.kubeconfig"
add_ignore "kubeconfig"
add_ignore "token*"
add_ignore "*-token*"
add_ignore ".local-secrets/"

echo
echo "==> 2. Remove tracked backup files"

TRACKED_BACKUPS="$(git ls-files | grep -E '(\.bak(\.|$)|\.backup$|\.tmp$|~$)' || true)"

if [ -n "$TRACKED_BACKUPS" ]; then
  echo "$TRACKED_BACKUPS"
  while IFS= read -r f; do
    [ -n "$f" ] && git rm -f --ignore-unmatch "$f"
  done <<< "$TRACKED_BACKUPS"
else
  echo "No tracked backup files."
fi

echo
echo "==> 3. Remove untracked backup files"

find . \
  -path ./.git -prune -o \
  \( -name "*.bak" -o -name "*.bak.*" -o -name "*.backup" -o -name "*.tmp" -o -name "*~" \) \
  -print > /tmp/apollo-git-cleanup/untracked-backups.txt

if [ -s /tmp/apollo-git-cleanup/untracked-backups.txt ]; then
  cat /tmp/apollo-git-cleanup/untracked-backups.txt
  while IFS= read -r f; do
    rm -rf "$f"
  done < /tmp/apollo-git-cleanup/untracked-backups.txt
else
  echo "No untracked backup files."
fi

echo
echo "==> 4. Sanitize Grafana password"

if [ -f observability/grafana/grafana.yaml ]; then
  python3 - <<'PY'
from pathlib import Path

p = Path("observability/grafana/grafana.yaml")
text = p.read_text()

out = []
for line in text.splitlines():
    stripped = line.lstrip()
    indent = line[:len(line) - len(stripped)]
    if stripped.startswith("admin_password:"):
        out.append(f'{indent}admin_password: "${{GRAFANA_ADMIN_PASSWORD}}"')
    else:
        out.append(line)

p.write_text("\n".join(out) + "\n")
PY

  mkdir -p observability/grafana
  cat > observability/grafana/grafana.env.example <<'ENVEOF'
GRAFANA_ADMIN_PASSWORD=change-me
ENVEOF
fi

echo
echo "==> 5. Secret scan"

grep -RInE 'sha256~|token=|Authorization:|client_secret|access_key|secret_key|BEGIN PRIVATE KEY|admin_password:|password:|passwd:' . \
  --exclude-dir=.git \
  --exclude-dir=node_modules \
  --exclude-dir=__pycache__ \
  --exclude-dir=.local-secrets \
  --exclude='*.png' \
  --exclude='*.jpg' \
  --exclude='*.jpeg' \
  --exclude='*.pdf' \
  --exclude='prepare-git-for-redeploy.sh' \
  > /tmp/apollo-git-cleanup/secret-scan.txt || true

grep -Ev 'GRAFANA_ADMIN_PASSWORD|change-me|Do not commit real secrets' \
  /tmp/apollo-git-cleanup/secret-scan.txt \
  > /tmp/apollo-git-cleanup/secret-scan.filtered.txt || true

if [ -s /tmp/apollo-git-cleanup/secret-scan.filtered.txt ]; then
  echo "ERROR: possible real secret found:"
  cat /tmp/apollo-git-cleanup/secret-scan.filtered.txt
  exit 1
fi

echo "Secret scan OK."

echo
echo "==> 6. Stage redeployable assets"

git add \
  .gitignore \
  README.md \
  applications \
  bootstrap \
  data \
  docs \
  evaluations \
  gitops \
  guardrails \
  lab-guide \
  observability \
  pipelines \
  policies \
  prompts \
  reset

echo
echo "==> 7. Check staged diff for secrets"

git diff --cached -- . ':(exclude)bootstrap/prepare-git-for-redeploy.sh' \
  | grep -Ei 'sha256~|token=|Authorization:|client_secret|access_key|secret_key|BEGIN PRIVATE KEY' \
  > /tmp/apollo-git-cleanup/staged-secret-scan.txt || true

if [ -s /tmp/apollo-git-cleanup/staged-secret-scan.txt ]; then
  echo "ERROR: secret-like value in staged diff:"
  cat /tmp/apollo-git-cleanup/staged-secret-scan.txt
  exit 1
fi

git diff --cached -- . ':(exclude)bootstrap/prepare-git-for-redeploy.sh' \
  | grep -Ei 'password|passwd' \
  > /tmp/apollo-git-cleanup/staged-password-lines.txt || true

if [ -s /tmp/apollo-git-cleanup/staged-password-lines.txt ]; then
  echo "Password-related staged lines:"
  cat /tmp/apollo-git-cleanup/staged-password-lines.txt

  grep -Ev 'GRAFANA_ADMIN_PASSWORD|change-me|Do not commit real secrets' \
    /tmp/apollo-git-cleanup/staged-password-lines.txt \
    > /tmp/apollo-git-cleanup/staged-password-lines.filtered.txt || true

  if [ -s /tmp/apollo-git-cleanup/staged-password-lines.filtered.txt ]; then
    echo "ERROR: possible real password in staged diff."
    cat /tmp/apollo-git-cleanup/staged-password-lines.filtered.txt
    exit 1
  fi
fi

echo "Staged secret scan OK."

echo
echo "==> 8. Check RHDP-specific URLs in staged deployable files"

git diff --cached --name-only \
  | grep -E '\.(yaml|yml|json|sh)$' \
  | grep -Ev 'cluster-inventory|docs/|lab-guide/|bootstrap/prepare-git-for-redeploy.sh' \
  | while read -r file; do
      [ -f "$file" ] || continue
      grep -HnEi '5hd6r|sandbox512|opentlc|apps\.ocp|api\.ocp' "$file" || true
    done > /tmp/apollo-git-cleanup/rhdp-urls.txt || true

if [ -s /tmp/apollo-git-cleanup/rhdp-urls.txt ]; then
  echo "ERROR: RHDP-specific URLs found in staged deployable files:"
  cat /tmp/apollo-git-cleanup/rhdp-urls.txt
  echo
  echo "Fix these before commit, or set ALLOW_RHDP_URLS=1 if intentional."
  if [ "${ALLOW_RHDP_URLS:-0}" != "1" ]; then
    exit 1
  fi
fi

echo "RHDP URL check OK."

echo
echo "==> 9. Final staged summary"

git status --short
echo
git diff --cached --stat

if [ "$COMMIT" = "true" ]; then
  echo
  echo "==> 10. Commit"
  if git diff --cached --quiet; then
    echo "Nothing staged."
  else
    git commit -m "Make Apollo Agent Lifecycle lab redeployable"
  fi
else
  echo
  echo "Dry run complete. No commit done."
  echo "To commit:"
  echo "  bash bootstrap/prepare-git-for-redeploy.sh --commit"
fi

if [ "$PUSH" = "true" ]; then
  echo
  echo "==> 11. Push"
  git push origin "$(git branch --show-current)"
else
  echo "To push:"
  echo "  git push origin $(git branch --show-current)"
fi

echo
echo "DONE"
