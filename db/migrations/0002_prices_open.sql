-- Paper fills execute at the NEXT session's open (PLAN.md §4 — no look-ahead),
-- so the prices table needs the open. Nullable: pre-existing rows lack it.
alter table prices add column open numeric check (open > 0);
