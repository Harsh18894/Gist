"""Gist local RAG maintenance: import sources or, after approval, embed them."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import connection, initialize  # noqa: E402
from app.config import database_path  # noqa: E402
from app.rag.ingest import import_file  # noqa: E402
from app.rag.provider import PaidApiDisabled, index_missing_embeddings  # noqa: E402
from app.rag.budget import reconcile as reconcile_spend, summary as spend_summary  # noqa: E402
from preflight_v2 import DB as V2_DB, preflight  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Gist synthetic-source RAG maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import", help="Import a synthetic CSV, TXT, or Markdown file")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--segment")
    ingest.add_argument("--product-area")
    ingest.add_argument("--source-date", help="YYYY-MM-DD")
    commands.add_parser("index-preflight", help="Read-only v2 index and cost checks")
    commands.add_parser("spend-report", help="Show the shared project reservation and usage summary")
    reconcile = commands.add_parser("reconcile-spend", help="Release an uncertain reservation after checking provider billing")
    reconcile.add_argument("--request-id", required=True)
    reconcile.add_argument("--actual-usd", type=float, required=True)
    reconcile.add_argument("--provider-confirmed", action="store_true")
    paid = commands.add_parser("embed-openai", help="Paid: persist text-embedding-3-small vectors")
    paid.add_argument("--confirm-paid", action="store_true", help="Confirm prior user approval and operator opt-in")
    args = parser.parse_args()
    if args.command == "index-preflight":
        import json
        report = preflight()
        print(json.dumps({"status": report["status"], "issues": report["issues"],
                          "index": report["index"], "embedding_cost_estimate_usd_at_0_02_per_m":
                          report["embedding_cost_estimate_usd_at_0_02_per_m"]}, indent=2))
        return
    if args.command == "spend-report":
        import json
        print(json.dumps(spend_summary(), indent=2))
        return
    if args.command == "reconcile-spend":
        if not args.provider_confirmed:
            parser.error("Check the provider billing record, then pass --provider-confirmed.")
        reconcile_spend(args.request_id, args.actual_usd)
        print("Uncertain request reconciled against the operator-confirmed provider charge.")
        return
    if args.command == "embed-openai":
        if not args.confirm_paid:
            parser.error("Paid indexing needs --confirm-paid after explicit approval.")
        if database_path().resolve() != V2_DB.resolve():
            parser.error("Paid v2 indexing requires GIST_DATASET_VERSION=v2 and the standard v2 database path.")
        report = preflight()
        if report["status"] != "PASS" or report["index"]["chunks"] != 536 or report["index"]["dataset_version"] != "v2":
            parser.error("Pulse v2 index preflight failed or did not contain exactly 536 chunks.")
    with connection() as db:
        initialize(db)
        if args.command == "import":
            with db:
                sources, chunks = import_file(db, args.path, segment=args.segment,
                                              product_area=args.product_area, source_date=args.source_date)
            print(f"Imported {sources} synthetic sources in {chunks} chunks.")
        else:
            try:
                count = index_missing_embeddings(db)
            except PaidApiDisabled as exc:
                parser.error(str(exc))
            print(f"Indexed {count} OpenAI embeddings. Review /api/usage for measured token use and estimated spend.")


if __name__ == "__main__":
    main()
