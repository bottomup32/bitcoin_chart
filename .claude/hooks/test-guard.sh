#!/bin/bash
# guard-portfolio-data.sh 회귀 테스트. 훅을 고쳤으면 이걸 돌린다.
#
# 이 훅은 자기 자신을 막아 개발을 세울 수 있다 — 실제로 두 번 그랬다:
# 파일 패턴이 core/lots.py를 잡았고, force-add 검사가 따옴표 안에 든 자기
# 문자열을 잡았다. 아래 pass 케이스 두 개가 그 회귀를 지킨다.
#
# 이 스크립트 자체에는 훅이 찾는 리터럴이 통째로 들어가면 안 되므로
# 문자열을 쪼개서 조립한다.
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
HOOK=".claude/hooks/guard-portfolio-data.sh"

G="git ad""d"
FORCE="-""f"
fails=0

check() { # 이름 기대값(BLOCK|pass) 명령
  local name="$1" expect="$2" cmd="$3" got
  local payload
  payload="$(printf '%s' "$cmd" | python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.stdin.read()}}))')"
  if printf '%s' "$payload" | "$HOOK" | grep -q '"deny"'; then got=BLOCK; else got=pass; fi
  if [ "$got" = "$expect" ]; then
    echo "ok   $name ($got)"
  else
    echo "FAIL $name: expected $expect, got $got"
    fails=$((fails + 1))
  fi
}

# 막아야 하는 것
check "force add"                 BLOCK "$G $FORCE lots.csv"
check "force add after &&"        BLOCK "cd /x && $G --force data/a.csv"

# 통과시켜야 하는 것 (과거 오탐)
check "quoted inside settings"    pass  "echo 'Bash($G $FORCE:*)' > .claude/settings.json"
check "source file named lots"    pass  "$G core/lots.py"
check "plain add"                 pass  "$G CLAUDE.md"
check "unrelated command"         pass  "uv run pytest"

# 스테이징된 데이터 파일 (.gitignore가 놓치는 확장자)
tmp="holdings.xlsx"
printf 'x' > "$tmp"
git add "$tmp" >/dev/null 2>&1
check "staged data file"          BLOCK "git commit -m x"
git restore --staged "$tmp" >/dev/null 2>&1
rm -f "$tmp"

if [ "$fails" -gt 0 ]; then
  echo "$fails 건 실패"
  exit 1
fi
echo "전부 통과"
