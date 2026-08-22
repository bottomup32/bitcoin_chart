#!/bin/bash
# PreToolUse(Bash) guard — PLAN.md §6 "데이터 유출 방지".
#
# This repo is public, but the DB behind it holds real lots, cost basis and
# account activity. .gitignore covers *.csv / data/ / .env, yet a `git add -f`
# or a stray path outside those patterns can still stage them. This hook denies
# any git staging/commit that would put portfolio data into the history.
set -euo pipefail

payload="$(cat)"

command="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    print("")
')"

# Only interested in commands that can write to git history.
case "$command" in
  *"git add"*|*"git commit"*|*"git stash"*) ;;
  *) exit 0 ;;
esac

deny() {
  python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": sys.argv[1],
}}))' "$1"
  exit 0
}

# 1. Force-adding bypasses .gitignore entirely — never allowed here.
# 명령이 실제로 시작되는 위치의 git 호출만 본다. 따옴표 안에 든 같은 문자열
# (권한 설정 파일을 편집하는 명령 등)까지 막으면 훅이 제 발등을 찍는다.
if printf '%s' "$command" | grep -Eq '(^|[;&|]|\$\()[[:space:]]*git +add +[^|;&]*(-f|--force)([[:space:]]|$)'; then
  deny "차단: 'git add -f'는 .gitignore를 우회한다. 포트폴리오 데이터(*.csv, data/, .env)는 커밋 금지 (PLAN.md §6)."
fi

# 2. Anything already staged that looks like portfolio/secret data.
staged="$(git diff --cached --name-only 2>/dev/null || true)"
if [ -n "$staged" ]; then
  # 데이터 파일만 잡는다 — core/lots.py 같은 소스 파일이 걸리면 안 된다.
  # .env.example 류는 값 없는 참조 파일이라 커밋 대상이다 (main 참조).
  offenders="$(printf '%s\n' "$staged" \
    | grep -Eiv '(^|/)\.env\.(example|sample|template)$' \
    | grep -Ei \
    -e '(^|/)data/' \
    -e '(^|/)knowledge/' \
    -e '(^|/)\.env($|\.)' \
    -e '\.(csv|tsv)$' \
    -e '(^|/)(lots|activity|positions|holdings)[^/]*\.(json|txt|xlsx?)$' || true)"
  if [ -n "$offenders" ]; then
    deny "차단: 포트폴리오·시크릿으로 보이는 파일이 스테이징돼 있다 — $(printf '%s' "$offenders" | tr '\n' ' '). 'git restore --staged <파일>'로 내린 뒤 다시 시도할 것 (PLAN.md §6)."
  fi
fi

exit 0
