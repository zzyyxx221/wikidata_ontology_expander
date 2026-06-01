from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import ExpansionEngine, load_config, load_seeds
from .fixture_client import FixtureWikidataClient
from .refinement import apply_changeset_to_outputs, load_changeset, run_iterative_refinement
from .taxonomy import TaxonomyReference
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
    expand.add_argument(
        "--taxonomy-excel",
        type=Path,
        help="Excel taxonomy reference used to constrain proposals to existing industry/product context.",
    )

    corpus = subparsers.add_parser(
        "expand-corpus",
        help="Generate ontology expansion changes from a Wikidata-like entity corpus without seed search.",
    )
    corpus.add_argument("--schema", required=True, type=Path, help="Path to seed ontology schema.")
    corpus.add_argument("--config", required=True, type=Path, help="JSON expansion config.")
    corpus.add_argument("--output", required=True, type=Path, help="Output ChangeSet JSON path.")
    corpus.add_argument(
        "--offline-fixture",
        required=True,
        type=Path,
        help="Local Wikidata fixture JSON containing entities to route.",
    )
    corpus.add_argument(
        "--taxonomy-excel",
        type=Path,
        help="Excel taxonomy reference used to constrain proposals to existing industry/product context.",
    )

    apply_changes = subparsers.add_parser(
        "apply-changes",
        help="Apply an accepted schema changeset back into schema/config outputs.",
    )
    apply_changes.add_argument("--schema", required=True, type=Path, help="Path to the current ontology schema.")
    apply_changes.add_argument("--config", required=True, type=Path, help="Path to the current expansion config.")
    apply_changes.add_argument("--changes", required=True, type=Path, help="Accepted changeset JSON path.")
    apply_changes.add_argument("--schema-output", required=True, type=Path, help="Output schema path after applying changes.")
    apply_changes.add_argument("--config-output", required=True, type=Path, help="Output config path after applying changes.")

    iterate = subparsers.add_parser(
        "iterate",
        help="Run multi-round schema refinement from seeds and automatically apply accepted proposals.",
    )
    iterate.add_argument("--schema", required=True, type=Path, help="Path to the current ontology schema.")
    iterate.add_argument("--seeds", required=True, type=Path, help="JSON seed entities.")
    iterate.add_argument("--config", required=True, type=Path, help="Path to the current expansion config.")
    iterate.add_argument("--output-dir", required=True, type=Path, help="Directory for round-by-round outputs.")
    iterate.add_argument("--rounds", type=int, default=3, help="Maximum refinement rounds.")
    iterate.add_argument("--accept-threshold", type=float, default=0.72, help="Auto-accept confidence threshold.")
    iterate.add_argument("--timeout", type=int, default=60, help="Wikidata request timeout in seconds.")
    iterate.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Skip failed Wikidata requests instead of stopping the whole run.",
    )
    iterate.add_argument(
        "--offline-fixture",
        type=Path,
        help="Use a local Wikidata fixture JSON instead of calling wikidata.org.",
    )
    iterate.add_argument(
        "--include-review-required",
        action="store_true",
        help="Also auto-accept proposals that still require review if they pass the confidence threshold.",
    )

    iterate_corpus = subparsers.add_parser(
        "iterate-corpus",
        help="Run multi-round schema refinement from a local corpus and automatically apply accepted proposals.",
    )
    iterate_corpus.add_argument("--schema", required=True, type=Path, help="Path to the current ontology schema.")
    iterate_corpus.add_argument("--config", required=True, type=Path, help="Path to the current expansion config.")
    iterate_corpus.add_argument("--output-dir", required=True, type=Path, help="Directory for round-by-round outputs.")
    iterate_corpus.add_argument("--offline-fixture", required=True, type=Path, help="Local Wikidata fixture JSON.")
    iterate_corpus.add_argument("--rounds", type=int, default=3, help="Maximum refinement rounds.")
    iterate_corpus.add_argument("--accept-threshold", type=float, default=0.72, help="Auto-accept confidence threshold.")
    iterate_corpus.add_argument(
        "--include-review-required",
        action="store_true",
        help="Also auto-accept proposals that still require review if they pass the confidence threshold.",
    )

    args = parser.parse_args()
    if args.command == "expand":
        config = load_config(args.config, args.schema)
        seeds = load_seeds(args.seeds)
        if args.offline_fixture:
            client = FixtureWikidataClient(args.offline_fixture)
        else:
            client = WikidataClient(language=config.language, timeout=args.timeout)
        taxonomy_reference = TaxonomyReference.load(args.taxonomy_excel) if args.taxonomy_excel else None
        engine = ExpansionEngine(
            client=client,
            config=config,
            continue_on_error=args.continue_on_error,
            taxonomy_reference=taxonomy_reference,
            incremental_output_path=args.output,
        )
        changeset = engine.expand(args.schema, seeds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(changeset.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {len(changeset.changes)} changes to {args.output}")
        if changeset.report is not None:
            report = changeset.report
            print(
                "Refinement report: "
                f"{report.classified_candidates}/{report.total_candidates} classified, "
                f"{report.unclassified_candidates} unclassified, "
                f"{report.module_free_candidates} module-free"
            )
            if report.uncovered_categories:
                print(f"Uncovered categories: {', '.join(report.uncovered_categories)}")
            if report.uncovered_modules:
                print(f"Uncovered modules: {', '.join(report.uncovered_modules)}")
    elif args.command == "expand-corpus":
        config = load_config(args.config, args.schema)
        client = FixtureWikidataClient(args.offline_fixture)
        taxonomy_reference = TaxonomyReference.load(args.taxonomy_excel) if args.taxonomy_excel else None
        engine = ExpansionEngine(
            client=client,
            config=config,
            taxonomy_reference=taxonomy_reference,
            incremental_output_path=args.output,
        )
        changeset = engine.expand_corpus(args.schema, client.all_entities())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(changeset.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {len(changeset.changes)} changes to {args.output}")
        if changeset.report is not None:
            report = changeset.report
            print(
                "Refinement report: "
                f"{report.classified_candidates}/{report.total_candidates} classified, "
                f"{report.unclassified_candidates} unclassified, "
                f"{report.module_free_candidates} module-free"
            )
            if report.uncovered_categories:
                print(f"Uncovered categories: {', '.join(report.uncovered_categories)}")
            if report.uncovered_modules:
                print(f"Uncovered modules: {', '.join(report.uncovered_modules)}")
    elif args.command == "apply-changes":
        changeset = load_changeset(args.changes)
        apply_changeset_to_outputs(args.schema, args.config, changeset, args.schema_output, args.config_output)
        print(f"Applied {len(changeset.changes)} changes to {args.schema_output} and {args.config_output}")
    elif args.command == "iterate":
        summary = run_iterative_refinement(
            mode="expand",
            schema_path=args.schema,
            config_path=args.config,
            output_dir=args.output_dir,
            rounds=args.rounds,
            accept_threshold=args.accept_threshold,
            seeds_path=args.seeds,
            offline_fixture=args.offline_fixture,
            timeout=args.timeout,
            continue_on_error=args.continue_on_error,
            include_review_required=args.include_review_required,
        )
        print(f"Final schema: {summary['final_schema']}")
        print(f"Final config: {summary['final_config']}")
        print(f"Rounds completed: {len(summary['rounds'])}")
    elif args.command == "iterate-corpus":
        summary = run_iterative_refinement(
            mode="expand-corpus",
            schema_path=args.schema,
            config_path=args.config,
            output_dir=args.output_dir,
            rounds=args.rounds,
            accept_threshold=args.accept_threshold,
            offline_fixture=args.offline_fixture,
            include_review_required=args.include_review_required,
        )
        print(f"Final schema: {summary['final_schema']}")
        print(f"Final config: {summary['final_config']}")
        print(f"Rounds completed: {len(summary['rounds'])}")


if __name__ == "__main__":
    main()
