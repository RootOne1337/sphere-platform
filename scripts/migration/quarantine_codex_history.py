"""Quarantine exactly two invalid rows from a verified SAVED history candidate.

This creates no full database copy and never installs anything into Codex. The
saved source, pre-salvage receipt, and raw journals must remain available.
Output and quarantine contain private history metadata and belong in a private
directory. A structurally valid partial candidate is not a full recovery.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import itertools
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def private_value(v):
    return (
        {"type": "bytes", "base64": base64.b64encode(v).decode("ascii")}
        if isinstance(v, bytes)
        else v
    )


def schema(db):
    rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")
    return [tuple(v.replace("\r\n", "\n") if isinstance(v, str) else v for v in r) for r in rows]


def fk(db):
    return list(db.execute("PRAGMA foreign_key_check"))


def compare_nonitems(src, dst):
    names = [
        x[0] for x in src.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
    ]
    other = [n for n in names if n != "thread_items"]
    for n in other:
        if not n.replace("_", "").isalnum():
            raise ValueError("Unsupported table name")
        query = f'SELECT * FROM "{n}" ORDER BY rowid'
        sentinel = object()
        if any(
            a != b
            for a, b in itertools.zip_longest(
                src.execute(query), dst.execute(query), fillvalue=sentinel
            )
        ):
            raise ValueError("Non-item table mismatch")
    return other


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="saved original snapshot, not live DB"
    )
    parser.add_argument("--candidate", type=Path, required=True, help="saved candidate.sqlite")
    parser.add_argument("--receipt", type=Path, required=True, help="pre-salvage receipt.json")
    parser.add_argument("--expected-invalid", type=int, required=True, choices=[2])
    args = parser.parse_args()
    original = args.source.resolve(strict=True)
    candidate = args.candidate.resolve(strict=True)
    provenance = args.receipt.resolve(strict=True)
    codex_home = (Path.home() / ".codex").resolve()
    if any(
        p == codex_home or p.is_relative_to(codex_home) for p in (original, candidate, provenance)
    ):
        raise ValueError("Live Codex home is forbidden")
    if (
        candidate.name != "candidate.sqlite"
        or provenance.name != "receipt.json"
        or provenance.parent != candidate.parent
    ):
        raise ValueError("Expected saved candidate.sqlite and sibling receipt.json")
    if (
        not original.name.endswith(".sqlite.snapshot.tmp")
        or original == candidate
        or original == provenance
    ):
        raise ValueError("Expected a distinct saved source .sqlite.snapshot.tmp")
    if any(p.is_symlink() for p in (args.source, args.candidate, args.receipt)):
        raise ValueError("Symlinked inputs are forbidden")
    if candidate.with_name(candidate.name + "-wal").exists():
        raise ValueError("Candidate has WAL; preserve and inspect it before quarantine")
    source_wal = original.with_name(original.name + "-wal")
    if source_wal.exists() and source_wal.stat().st_size:
        raise ValueError("Source has a nonempty WAL; a main-file hash is not a complete snapshot")
    qpath = candidate.parent / "quarantined-items.private.json"
    rpath = candidate.parent / "partial-salvage-receipt.private.json"
    if qpath.exists() or rpath.exists():
        raise ValueError("Output already exists; preserve previous evidence")
    receipt = json.loads(provenance.read_text(encoding="utf8"))
    source_hash = digest(original)
    before_hash = digest(candidate)
    if receipt.get("sourceSha256") != source_hash or receipt.get("candidateSha256") != before_hash:
        raise ValueError("Saved source/candidate do not match prior receipt hashes")

    src = sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(candidate.as_uri() + "?mode=rw", uri=True)
    try:
        dst.execute("PRAGMA foreign_keys=ON")
        dst.execute("BEGIN IMMEDIATE")
        if schema(src) != schema(dst) or dst.execute("PRAGMA integrity_check").fetchall() != [
            ("ok",)
        ]:
            raise ValueError("Candidate integrity or schema mismatch")
        source_fk, before_fk = fk(src), fk(dst)
        if source_fk != before_fk:
            raise ValueError("Source and candidate foreign key checks differ")
        other = compare_nonitems(src, dst)
        rows = dst.execute(
            "SELECT rowid,* FROM thread_items WHERE NOT json_valid(item_json)"
        ).fetchall()
        columns = [
            d[0] for d in dst.execute("SELECT rowid,* FROM thread_items LIMIT 0").description
        ]
        if len(rows) != args.expected_invalid:
            raise ValueError("Unexpected number of invalid rows")
        damaged = {r[0] for r in rows}
        indexed = list(
            src.execute(
                "SELECT rowid,thread_id,turn_id,rollout_ordinal FROM thread_items INDEXED BY idx_thread_items_by_turn_page"
            )
        )
        actual = set(
            dst.execute("SELECT rowid,thread_id,turn_id,rollout_ordinal FROM thread_items")
        )
        if len(indexed) != len(actual) or set(indexed) != actual:
            raise ValueError("Candidate keys do not match source index")
        index_evidence = []
        for r in rows:
            row = dict(zip(columns, r))
            identity = list(
                src.execute(
                    "SELECT item_id,rowid FROM thread_items INDEXED BY sqlite_autoindex_thread_items_1 WHERE thread_id=? AND turn_id=?",
                    (row["thread_id"], row["turn_id"]),
                )
            )
            updates = list(
                src.execute(
                    "SELECT updated_at_ordinal,rowid FROM thread_items INDEXED BY idx_thread_items_by_turn_updated_page WHERE thread_id=? AND turn_id=?",
                    (row["thread_id"], row["turn_id"]),
                )
            )
            matching_identity = [x for x in identity if x[1] == row["rowid"]]
            matching_updates = [x for x in updates if x[1] == row["rowid"]]
            if matching_identity != [(row["item_id"], row["rowid"])] or len(matching_updates) != 1:
                raise ValueError("Source index does not prove selected row identity")
            index_evidence.append(
                {
                    "rowid": row["rowid"],
                    "itemId": row["item_id"],
                    "sourceUpdatedOrdinal": matching_updates[0][0],
                }
            )
        verified = 0
        for rowid, _, _, _ in indexed:
            if rowid in damaged:
                try:
                    src.execute(
                        "SELECT rowid,* FROM thread_items WHERE rowid=?", (rowid,)
                    ).fetchone()
                except sqlite3.DatabaseError:
                    continue
                raise ValueError("Selected source row is readable; no quarantine permitted")
            if (
                src.execute("SELECT rowid,* FROM thread_items WHERE rowid=?", (rowid,)).fetchone()
                != dst.execute(
                    "SELECT rowid,* FROM thread_items WHERE rowid=?", (rowid,)
                ).fetchone()
            ):
                raise ValueError("A retained source row differs from candidate")
            verified += 1
        evidence = {
            "private": True,
            "sourceSha256": source_hash,
            "candidateBeforeSha256": before_hash,
            "rows": [{k: private_value(v) for k, v in zip(columns, r)} for r in rows],
            "sourceIndexEvidence": index_evidence,
            "note": "Damaged source records; no reconstruction inferred.",
        }
        with qpath.open("x", encoding="utf8") as f:
            json.dump(evidence, f, ensure_ascii=False, indent=2)
            f.write("\n")
        dst.executemany("DELETE FROM thread_items WHERE rowid=?", [(x,) for x in sorted(damaged)])
        if (
            dst.execute(
                "SELECT count(*) FROM thread_items WHERE NOT json_valid(item_json)"
            ).fetchone()[0]
            != 0
        ):
            raise ValueError("Invalid JSON remains")
        if dst.execute("SELECT count(*) FROM thread_items").fetchone()[0] != verified:
            raise ValueError("Retained item count mismatch")
        for rowid, _, _, _ in indexed:
            if rowid not in damaged:
                source_row = src.execute(
                    "SELECT rowid,* FROM thread_items WHERE rowid=?", (rowid,)
                ).fetchone()
                retained_row = dst.execute(
                    "SELECT rowid,* FROM thread_items WHERE rowid=?", (rowid,)
                ).fetchone()
                if source_row != retained_row:
                    raise ValueError("A retained row changed after quarantine")
        if (
            fk(dst) != source_fk
            or schema(src) != schema(dst)
            or compare_nonitems(src, dst) != other
        ):
            raise ValueError("Post-quarantine schema, foreign keys or tables changed")
        if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Post-quarantine integrity check failed")
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    result = {
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "private": True,
        "sourceSha256": source_hash,
        "candidateBeforeSha256": before_hash,
        "candidateAfterSha256": digest(candidate),
        "quarantineSha256": digest(qpath),
        "sourceIndexCount": len(indexed),
        "retainedRowsExactlyVerified": verified,
        "omittedDamagedRows": len(damaged),
        "invalidItemJson": 0,
        "integrityOk": True,
        "schemaPreserved": True,
        "otherTablesPreserved": len(other),
        "sourceForeignKeyViolations": len(source_fk),
        "candidateForeignKeyViolations": len(source_fk),
        "installed": False,
        "completeRecoveryProven": False,
        "limit": "Partial salvage: two unrecoverable original rows omitted and quarantined. Application compatibility and offline installation not established.",
    }
    with rpath.open("x", encoding="utf8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("sourceSha256", "candidateBeforeSha256", "quarantineSha256")
            }
        )
    )


if __name__ == "__main__":
    main()
