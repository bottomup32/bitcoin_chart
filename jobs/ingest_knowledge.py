"""Local-only knowledge CLI — builds the investor-philosophy corpus.

Runs on the user's machine and upserts straight to Supabase, the same posture
as jobs/ingest_portfolio.py. Never runs in CI: it costs LLM tokens, it needs
human review, and the source material may be copyrighted.

Commands:
  python -m jobs.ingest_knowledge source-add --name "Howard Marks memos" \
                                             --url https://... --prior 0.6
  python -m jobs.ingest_knowledge add    --source "Howard Marks memos" --url https://...
  python -m jobs.ingest_knowledge add    --source "..." --file knowledge/marks.txt
  python -m jobs.ingest_knowledge add    --source "..." --stdin --title "..."
  python -m jobs.ingest_knowledge chunk  --doc-id 3       # one LLM call -> draft chunks
  python -m jobs.ingest_knowledge review --doc-id 3       # print drafts to check
  python -m jobs.ingest_knowledge approve --doc-id 3 [--chunk-ids 4,5]
  python -m jobs.ingest_knowledge stats

Cost: roughly one 20K-input Sonnet call per document, about $0.04-0.06 — call it
$1 one-time for twenty documents, against a ~$0.70/month baseline. Logged to
llm_calls with purpose='knowledge_ingest'.

Chunks are paraphrased 30-80 word decision rules, never verbatim excerpts. That
is cheaper AND cleaner on copyright: the repo is public and the source may be a
book or a paywalled letter, so storing long quotations in a DB and shipping them
to an API daily is a risk with no upside.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.llm_log import CallRecord, Usage, measure_chars, record_call
from core.memory import UNTRIGGERED_TAGS
from db.client import get_conn

MAX_DOC_CHARS = 200_000
MAX_BODY_CHARS = 400

# The controlled vocabulary. Retrieval only ever matches these, so a chunk
# tagged anything else is dead weight — the chunker is told so explicitly.
TAG_VOCABULARY = sorted(UNTRIGGERED_TAGS | {
    "drawdown", "high_volatility", "concentration", "correlation", "momentum",
    "mean_reversion", "unrealized_loss", "holding_period", "wash_sale", "thin_data",
})

CHUNKER_SYSTEM = f"""You extract decision rules from investment writing for a \
personal portfolio-advisory system.

Return short, opinionated, ACTIONABLE rules — not summaries. The reader is an \
analysis agent that already knows the famous investors' names and general \
reputations; restating those wastes its budget. What it needs is the specific \
rule, phrased so it can be applied to concrete numbers today.

  bad:  "Howard Marks emphasizes second-level thinking and cycle awareness."
  good: "In a drawdown with elevated volatility, ask whether price fell more \
than value. If so, reduce sizing rather than exiting."

Rules for every chunk:
- 30-80 words, at most {MAX_BODY_CHARS} characters. Hard limit.
- PARAPHRASE. Never reproduce more than a short phrase verbatim.
- One rule per chunk. If a passage contains three ideas, emit three chunks.
- Drop anything that is biography, market history, or general encouragement.
- tags: only from this list, and only when the rule genuinely applies to that \
situation: {', '.join(TAG_VOCABULARY)}
- horizons: which of days/weeks/months/quarters the rule is for. Leave empty \
only if it truly applies at every horizon — a rule about multi-year holding \
periods must NOT be tagged 'days'.
- agents: which of daily_signal/allocation/risk/tax should see it. Empty = all.
- layer: 'core' for a handful of foundational, situation-independent principles; \
'situational' for everything else. Prefer 'situational'.
- kind: 'principle' (what to believe), 'heuristic' (what to do), or 'caution' \
(what to avoid).

Extract at most 25 chunks. Fewer, sharper rules beat exhaustive coverage."""


class Chunk(BaseModel):
    body: str = Field(max_length=MAX_BODY_CHARS, description="30-80 words, paraphrased")
    kind: Literal["principle", "heuristic", "caution"]
    horizons: list[Literal["days", "weeks", "months", "quarters"]] = Field(default_factory=list)
    agents: list[Literal["daily_signal", "allocation", "risk", "tax"]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    layer: Literal["core", "situational"] = "situational"


class ChunkSet(BaseModel):
    chunks: list[Chunk]


def _source_id(cur, name: str) -> int:
    cur.execute("select id from sources where name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"source '{name}' not found — create it with source-add first")
    return row[0]


def cmd_source_add(args) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into sources (name, type, url, credibility_prior)
            values (%s, 'research', %s, %s)
            on conflict (name) do update
                set url = excluded.url, credibility_prior = excluded.credibility_prior
            returning id
            """,
            (args.name, args.url, args.prior),
        )
        print(f"source '{args.name}' -> id {cur.fetchone()[0]} (prior {args.prior})")
        conn.commit()


def _fetch(url: str) -> str:
    import requests

    # No HTML parser dependency: the chunking call reads HTML fine, and this
    # path runs a handful of times ever. Not worth a new dependency.
    response = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    })
    response.raise_for_status()
    return response.text


def cmd_add(args) -> None:
    if args.url:
        raw, origin = _fetch(args.url), "url"
    elif args.file:
        raw, origin = Path(args.file).read_text(), "file"
    else:
        raw, origin = sys.stdin.read(), "pasted"

    raw = raw.strip()
    if not raw:
        raise SystemExit("nothing to ingest")
    if len(raw) > MAX_DOC_CHARS:
        print(f"document is {len(raw)} chars; truncating to {MAX_DOC_CHARS}")
        raw = raw[:MAX_DOC_CHARS]

    sha = hashlib.sha256(raw.encode()).hexdigest()
    title = args.title or (args.url or args.file or "pasted document")

    with get_conn() as conn, conn.cursor() as cur:
        source_id = _source_id(cur, args.source)
        cur.execute(
            """
            insert into knowledge_docs (source_id, title, author, url, origin, content_sha, raw)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (content_sha) do nothing
            returning id
            """,
            (source_id, title, args.author, args.url, origin, sha, raw),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None:
            cur.execute("select id from knowledge_docs where content_sha = %s", (sha,))
            print(f"already ingested as doc {cur.fetchone()[0]} (identical content)")
            return
        print(f"doc {row[0]}: {len(raw)} chars stored. Next: chunk --doc-id {row[0]}")


def cmd_chunk(args) -> None:
    import anthropic

    from agents.base import PROMPT_VERSION, model_id

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select source_id, title, raw from knowledge_docs where id = %s", (args.doc_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"doc {args.doc_id} not found")
        source_id, title, raw = row

        cur.execute("select count(*) from knowledge_chunks where doc_id = %s", (args.doc_id,))
        if cur.fetchone()[0] and not args.replace:
            raise SystemExit(
                f"doc {args.doc_id} already has chunks — pass --replace to redo "
                "(this costs another LLM call)"
            )

        payload = {"title": title, "document": raw}
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model_id(),
            max_tokens=16000,
            system=CHUNKER_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            output_format=ChunkSet,
        )
        parsed = response.parsed_output
        record = CallRecord(
            usage=Usage.from_response(response),
            chars=measure_chars(CHUNKER_SYSTEM, payload),
            ok=parsed is not None,
        )
        record_call(cur, run_id=None, purpose="knowledge_ingest", model_id=model_id(),
                    prompt_version=PROMPT_VERSION, record=record)
        conn.commit()
        if parsed is None:
            raise SystemExit("chunker returned nothing")

        if args.replace:
            cur.execute("delete from knowledge_chunks where doc_id = %s", (args.doc_id,))

        kept = dropped = 0
        for seq, chunk in enumerate(parsed.chunks):
            body = chunk.body.strip()
            unknown = [t for t in chunk.tags if t not in TAG_VOCABULARY]
            tags = [t for t in chunk.tags if t in TAG_VOCABULARY]
            if not body or len(body) > MAX_BODY_CHARS or not tags:
                # An untagged chunk can never be retrieved, so storing it would
                # only inflate the corpus.
                dropped += 1
                continue
            if unknown:
                print(f"  chunk {seq}: dropped off-vocabulary tags {unknown}")
            cur.execute(
                """
                insert into knowledge_chunks
                    (doc_id, source_id, seq, body, kind, horizons, agents, tags,
                     layer, char_len, approved)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false)
                on conflict (doc_id, seq) do update
                    set body = excluded.body, kind = excluded.kind,
                        horizons = excluded.horizons, agents = excluded.agents,
                        tags = excluded.tags, layer = excluded.layer,
                        char_len = excluded.char_len, approved = false
                """,
                (args.doc_id, source_id, seq, body, chunk.kind, chunk.horizons,
                 chunk.agents, tags, chunk.layer, len(body)),
            )
            kept += 1
        conn.commit()
        print(f"doc {args.doc_id}: {kept} chunks drafted, {dropped} dropped "
              f"({record.usage.input_tokens} in / {record.usage.output_tokens} out tokens)")
        print(f"Nothing is live until you review it: review --doc-id {args.doc_id}")


def cmd_review(args) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id, seq, kind, layer, horizons, agents, tags, approved, body
            from knowledge_chunks where doc_id = %s order by seq
            """,
            (args.doc_id,),
        )
        rows = cur.fetchall()
        if not rows:
            raise SystemExit(f"doc {args.doc_id} has no chunks — run chunk first")
        for chunk_id, seq, kind, layer, horizons, agents, tags, approved, body in rows:
            mark = "✓" if approved else " "
            print(f"\n[{mark}] id={chunk_id} seq={seq} {kind}/{layer}")
            print(f"    horizons={horizons or 'any'} agents={agents or 'all'} tags={tags}")
            print(f"    {body}")
        print(f"\n{len(rows)} chunks, {sum(1 for r in rows if r[7])} approved.")
        print(f"Approve with: approve --doc-id {args.doc_id}")


def cmd_approve(args) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        if args.chunk_ids:
            ids = [int(x) for x in args.chunk_ids.split(",")]
            cur.execute(
                "update knowledge_chunks set approved = true where doc_id = %s and id = any(%s)",
                (args.doc_id, ids),
            )
        else:
            cur.execute(
                "update knowledge_chunks set approved = true where doc_id = %s", (args.doc_id,)
            )
        print(f"approved {cur.rowcount} chunks")
        conn.commit()


def cmd_stats(args) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select s.name, count(distinct d.id), count(c.id) filter (where c.approved),
                   count(c.id), coalesce(sum(c.char_len) filter (where c.approved), 0)
            from sources s
            left join knowledge_docs d on d.source_id = s.id
            left join knowledge_chunks c on c.doc_id = d.id
            where s.type = 'research'
            group by s.name order by s.name
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("no knowledge sources yet — start with source-add")
            return
        print(f"{'source':<32} {'docs':>5} {'live':>5} {'total':>6} {'chars':>7}")
        for name, docs, approved, total, chars in rows:
            print(f"{name:<32} {docs:>5} {approved:>5} {total:>6} {chars:>7}")

        cur.execute(
            """
            select layer, count(*), sum(char_len)
            from knowledge_chunks where approved group by layer order by layer
            """
        )
        print("\napproved by layer:")
        for layer, count, chars in cur.fetchall():
            print(f"  {layer:<12} {count:>4} chunks, {chars:>6} chars")

        cur.execute(
            "select unnest(tags) tag, count(*) from knowledge_chunks where approved"
            " group by tag order by 2 desc, 1"
        )
        covered = cur.fetchall()
        print("\ntag coverage:", ", ".join(f"{t}={n}" for t, n in covered) or "none")
        missing = sorted(set(TAG_VOCABULARY) - {t for t, _ in covered})
        if missing:
            print("uncovered tags (no chunk fires on these situations):", ", ".join(missing))


def main() -> int:
    parser = argparse.ArgumentParser(prog="ingest_knowledge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("source-add", help="register an investor / publication")
    p.add_argument("--name", required=True)
    p.add_argument("--url")
    p.add_argument("--prior", type=float, default=0.5,
                   help="credibility prior in [0,1]; used until n_eff >= 30")
    p.set_defaults(func=cmd_source_add)

    p = sub.add_parser("add", help="ingest one document")
    p.add_argument("--source", required=True)
    p.add_argument("--url")
    p.add_argument("--file")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--title")
    p.add_argument("--author")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("chunk", help="one LLM call: document -> draft decision rules")
    p.add_argument("--doc-id", type=int, required=True)
    p.add_argument("--replace", action="store_true", help="re-chunk (costs another call)")
    p.set_defaults(func=cmd_chunk)

    p = sub.add_parser("review", help="print drafts for human review")
    p.add_argument("--doc-id", type=int, required=True)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("approve", help="make chunks retrievable")
    p.add_argument("--doc-id", type=int, required=True)
    p.add_argument("--chunk-ids", help="comma-separated; omit to approve all")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("stats", help="corpus size, layers, tag coverage")
    p.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
