"""Run the offline RAG baseline against the golden set.

Every number in the report is produced by actually retrieving over the local
corpus. The dataset is synthetic and the embedder is a lexical baseline, both
of which are recorded in the output so the numbers cannot be mistaken for a
production benchmark.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.rag import (  # noqa: E402
    HashingEmbedder,
    RagRetriever,
    evaluate,
)

CORPUS = ROOT / "eval" / "golden" / "corpus.jsonl"
CASES = ROOT / "eval" / "golden" / "qa.jsonl"
REPORT = ROOT / "reports" / "rag-eval.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def main() -> int:
    corpus = load_jsonl(CORPUS)
    cases = load_jsonl(CASES)

    retriever = RagRetriever(embedder=HashingEmbedder(dim=256), chunk_size=240, overlap=40)
    chunk_count = retriever.index_documents(
        {row["doc_id"]: row["text"] for row in corpus}
    )

    report = evaluate(retriever, cases, k_values=(1, 3))
    report.update(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "synthetic": True,
            "dataset": "eval/golden (hand-written, synthetic)",
            "embedder": "hashing-256 (lexical baseline, not semantic)",
            "caveat": (
                "15 hand-written docs with lexically disjoint queries: the metrics "
                "saturate and prove the pipeline runs end to end, not retrieval quality. "
                "Meaningful numbers need a real corpus and human labels."
            ),
            "corpus_size": len(corpus),
            "chunk_count": chunk_count,
            "git_sha": git_sha(),
        }
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())