from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import ExpansionEngine, load_config, load_seeds
from .fixture_client import FixtureWikidataClient
from .wikidata import WikidataClient


def main() -> None:
    parser = argparse.ArgumentParser(prog="wikidata-ontology-expander")
    subparsers = parser.add_subparsers(dest="command", required=True)

    expand = subparsers.add_parser("expand", help="Generate ontology expansion changes from Wikidata.")
    expand.add_argument("--schema", required=True, type=Path, help="Path to seed ontology schema.")
    expand.add_argument("--seeds", required=True, type=Path, help="JSON seed entities.")
    expand.add_argument("--config", required=True, type=Path, help="JSON expansion config.")
    expand.add_argument("--output", required=True, type=Path, help="Output ChangeSet JSON path.")
    expand.add_argument("--timeout", type=int, default=60, help="Wikidata request timeout in seconds.")
    expand.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Skip failed Wikidata requests instead of stopping the whole run.",
    )
    expand.add_argument(
        "--offline-fixture",
        type=Path,
        help="Use a local Wikidata fixture JSON instead of calling wikidata.org.",
    )

    args = parser.parse_args()
    if args.command == "expand":
        config = load_config(args.config)
        seeds = load_seeds(args.seeds)
        if args.offline_fixture:
            client = FixtureWikidataClient(args.offline_fixture)
        else:
            client = WikidataClient(language=config.language, timeout=args.timeout)
        engine = ExpansionEngine(client=client, config=config, continue_on_error=args.continue_on_error)
        changeset = engine.expand(args.schema, seeds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(changeset.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {len(changeset.changes)} changes to {args.output}")


if __name__ == "__main__":
    main()
