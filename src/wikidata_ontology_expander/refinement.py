from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .engine import ExpansionEngine, load_config, load_seeds
from .fixture_client import FixtureWikidataClient
from .models import Change, ChangeSet, EntityType, Evidence, SchemaConceptType, SchemaDocument, SchemaDomain, SchemaField, SchemaModule
from .schema_parser import load_schema_document
from .wikidata import WikidataClient


def load_changeset(path: Path) -> ChangeSet:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ChangeSet(changes=[_change_from_dict(item) for item in data.get("changes", [])])


def auto_accept_changes(changeset: ChangeSet, min_confidence: float, include_review_required: bool = False) -> ChangeSet:
    accepted = []
    for change in changeset.changes:
        if change.confidence < min_confidence:
            continue
        if change.review_required and not include_review_required:
            continue
        accepted.append(change)
    return ChangeSet(changes=accepted)


def apply_changeset_to_outputs(
    schema_path: Path,
    config_path: Path,
    changeset: ChangeSet,
    schema_output: Path,
    config_output: Path,
) -> tuple[SchemaDocument, dict[str, Any]]:
    schema_doc = load_schema_document(schema_path, use_cache=False)
    updated_doc = apply_changeset_to_schema_document(schema_doc, changeset)
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    updated_config = apply_changeset_to_config_data(config_data, changeset)
    schema_output.parent.mkdir(parents=True, exist_ok=True)
    config_output.parent.mkdir(parents=True, exist_ok=True)
    schema_output.write_text(render_schema_document(updated_doc), encoding="utf-8")
    config_output.write_text(json.dumps(updated_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated_doc, updated_config


def apply_changeset_to_schema_document(schema_doc: SchemaDocument, changeset: ChangeSet) -> SchemaDocument:
    domains = list(schema_doc.domains)
    modules = list(schema_doc.modules)
    entities = dict(schema_doc.entities)
    entity_order = list(schema_doc.entities)

    for change in changeset.changes:
        if change.domain:
            domains = _ensure_domain(domains, change.domain, change.entity_type)
        if change.action == "add_concept":
            concept_name = _pascal_case(change.label)
            if concept_name not in entities:
                entities[concept_name] = EntityType(
                    name=concept_name,
                    label=change.label,
                    kind="ConceptType",
                    domain=change.domain,
                    fields=(),
                )
                entity_order.append(concept_name)
            continue
        if change.action == "add_category_gate":
            continue
        if change.action not in {"add_property_type", "add_relation_type", "add_module"}:
            continue
        owner_name = change.entity_type or "Thing"
        owner = entities.get(owner_name)
        if owner is None:
            owner = EntityType(name=owner_name, label=owner_name, kind="EntityType", domain=change.domain, fields=())
            entities[owner_name] = owner
            entity_order.append(owner_name)
        section = "relation" if _is_relation_change(change) else "property"
        field_name = change.field or _camel_case_fallback(change.label)
        field_label = _field_display_label(change, field_name)
        type_name = _schema_type_name(change, owner_name)
        module_name = change.module or _default_module_name(section)
        if any(field.name == field_name and field.section == section for field in owner.fields):
            continue
        new_field = SchemaField(
            owner=owner.name,
            section=section,
            name=field_name,
            label=field_label,
            type_name=type_name,
            module=module_name,
        )
        entities[owner_name] = replace(owner, fields=(*owner.fields, new_field))
        modules = _upsert_module(
            modules,
            domain=change.domain or owner.domain or "",
            module_name=module_name,
            entity_type=owner_name,
            field_name=field_name,
            section=section,
        )

    ordered_entities = {name: entities[name] for name in entity_order}
    concept_types = tuple(
        SchemaConceptType(name=entity.name, label=entity.label, kind=entity.kind)
        for entity in ordered_entities.values()
        if entity.kind == "ConceptType"
    )
    return SchemaDocument(
        concept_types=concept_types,
        domains=tuple(domains),
        modules=tuple(modules),
        entities=ordered_entities,
    )


def apply_changeset_to_config_data(config_data: dict[str, Any], changeset: ChangeSet) -> dict[str, Any]:
    updated = dict(config_data)
    updated.setdefault("property_map", {})
    modules = [dict(item) for item in updated.get("modules", [])]
    for change in changeset.changes:
        if not change.domain:
            continue
        profile = _ensure_profile(modules, change.domain, change.entity_type)
        if change.action == "add_category_gate" and change.label:
            labels = list(profile.get("category_gate_labels", []))
            if change.label not in labels:
                labels.append(change.label)
            profile["category_gate_labels"] = labels
            continue
        pid = _change_pid(change)
        if not pid or not change.field:
            continue
        if _is_relation_change(change):
            relation_properties = dict(profile.get("relation_properties", {}))
            relation_properties.setdefault(change.field, pid)
            profile["relation_properties"] = relation_properties
        else:
            property_map = dict(updated.get("property_map", {}))
            property_map.setdefault(change.field, pid)
            updated["property_map"] = property_map
    updated["modules"] = modules
    return updated


def render_schema_document(schema_doc: SchemaDocument) -> str:
    lines: list[str] = []
    domain_order = [domain.key for domain in schema_doc.domains]
    grouped = _group_entities_by_domain(schema_doc, domain_order)
    for domain_key in domain_order:
        entity_names = grouped.get(domain_key, [])
        if not entity_names:
            continue
        domain = next(domain for domain in schema_doc.domains if domain.key == domain_key)
        if lines:
            lines.append("")
        lines.append(f"# {domain.name}")
        lines.append("")
        for entity_name in entity_names:
            entity = schema_doc.entities[entity_name]
            lines.extend(_render_entity(entity))
            lines.append("")
    remainder = [name for name, entity in schema_doc.entities.items() if entity.domain not in set(domain_order)]
    for entity_name in remainder:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(_render_entity(schema_doc.entities[entity_name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_iterative_refinement(
    mode: str,
    schema_path: Path,
    config_path: Path,
    output_dir: Path,
    rounds: int,
    accept_threshold: float,
    seeds_path: Path | None = None,
    offline_fixture: Path | None = None,
    timeout: int = 60,
    continue_on_error: bool = False,
    include_review_required: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    current_schema = schema_path
    current_config = config_path
    summary_rounds: list[dict[str, Any]] = []
    for round_index in range(1, rounds + 1):
        config = load_config(current_config, current_schema)
        if mode == "expand":
            if seeds_path is None:
                raise ValueError("seeds_path is required for expand mode")
            seeds = load_seeds(seeds_path)
            if offline_fixture:
                client = FixtureWikidataClient(offline_fixture)
            else:
                client = WikidataClient(language=config.language, timeout=timeout)
            engine = ExpansionEngine(client=client, config=config, continue_on_error=continue_on_error)
            changeset = engine.expand(current_schema, seeds)
        elif mode == "expand-corpus":
            if offline_fixture is None:
                raise ValueError("offline_fixture is required for expand-corpus mode")
            client = FixtureWikidataClient(offline_fixture)
            engine = ExpansionEngine(client=client, config=config, continue_on_error=continue_on_error)
            changeset = engine.expand_corpus(current_schema, client.all_entities())
        else:
            raise ValueError(f"unsupported mode: {mode}")

        round_dir = output_dir / f"round_{round_index}"
        round_dir.mkdir(parents=True, exist_ok=True)
        changes_path = round_dir / "changeset.json"
        changes_path.write_text(json.dumps(changeset.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        accepted = auto_accept_changes(changeset, accept_threshold, include_review_required=include_review_required)
        accepted_path = round_dir / "accepted_changeset.json"
        accepted_path.write_text(json.dumps(accepted.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        round_summary = {
            "round": round_index,
            "changes": len(changeset.changes),
            "accepted": len(accepted.changes),
            "changes_path": str(changes_path),
            "accepted_path": str(accepted_path),
        }
        if not accepted.changes:
            summary_rounds.append(round_summary)
            break
        next_schema = round_dir / "schema.next.schema"
        next_config = round_dir / "config.next.json"
        apply_changeset_to_outputs(current_schema, current_config, accepted, next_schema, next_config)
        round_summary["schema_path"] = str(next_schema)
        round_summary["config_path"] = str(next_config)
        summary_rounds.append(round_summary)
        current_schema = next_schema
        current_config = next_config
    return {
        "final_schema": str(current_schema),
        "final_config": str(current_config),
        "rounds": summary_rounds,
    }


def _change_from_dict(data: dict[str, Any]) -> Change:
    return Change(
        action=data["action"],
        entity_type=data["entity_type"],
        label=data["label"],
        confidence=float(data["confidence"]),
        domain=data.get("domain"),
        module=data.get("module"),
        parent=data.get("parent"),
        field=data.get("field"),
        value=data.get("value"),
        target_type=data.get("target_type"),
        support=int(data.get("support", 0)),
        examples=tuple(data.get("examples", ())),
        rationale=data.get("rationale"),
        evidence=tuple(
            Evidence(
                source=item["source"],
                detail=item["detail"],
                weight=float(item["weight"]),
            )
            for item in data.get("evidence", ())
        ),
        source_entity_ids=tuple(data.get("source_entity_ids", ())),
        review_required=bool(data.get("review_required", False)),
    )


def _ensure_domain(domains: list[SchemaDomain], domain_key: str, entity_type: str) -> list[SchemaDomain]:
    for index, domain in enumerate(domains):
        if domain.key != domain_key:
            continue
        entity_types = list(domain.entity_types)
        if entity_type and entity_type not in entity_types:
            entity_types.append(entity_type)
            domains[index] = replace(domain, entity_types=tuple(entity_types))
        return domains
    domains.append(SchemaDomain(name=domain_key, key=domain_key, entity_types=(entity_type,) if entity_type else ()))
    return domains


def _upsert_module(
    modules: list[SchemaModule],
    domain: str,
    module_name: str,
    entity_type: str,
    field_name: str,
    section: str,
) -> list[SchemaModule]:
    for index, module in enumerate(modules):
        if module.domain != domain or module.name != module_name:
            continue
        entity_types = list(module.entity_types)
        if entity_type not in entity_types:
            entity_types.append(entity_type)
        property_fields = list(module.property_fields)
        relation_fields = list(module.relation_fields)
        if section == "property" and field_name not in property_fields:
            property_fields.append(field_name)
        if section == "relation" and field_name not in relation_fields:
            relation_fields.append(field_name)
        kind = _module_kind_from_fields(property_fields, relation_fields)
        modules[index] = replace(
            module,
            kind=kind,
            entity_types=tuple(entity_types),
            property_fields=tuple(property_fields),
            relation_fields=tuple(relation_fields),
        )
        return modules
    property_fields = (field_name,) if section == "property" else ()
    relation_fields = (field_name,) if section == "relation" else ()
    modules.append(
        SchemaModule(
            name=module_name,
            domain=domain,
            kind=_module_kind_from_fields(list(property_fields), list(relation_fields)),
            entity_types=(entity_type,) if entity_type else (),
            property_fields=property_fields,
            relation_fields=relation_fields,
        )
    )
    return modules


def _module_kind_from_fields(property_fields: list[str], relation_fields: list[str]) -> str:
    if relation_fields and property_fields:
        return "mixed"
    if relation_fields:
        return "relational"
    return "intrinsic"


def _ensure_profile(modules: list[dict[str, Any]], domain: str, entity_type: str) -> dict[str, Any]:
    for module in modules:
        if module.get("name") == domain:
            entity_types = list(module.get("entity_types", []))
            if entity_type and entity_type not in entity_types:
                entity_types.append(entity_type)
                module["entity_types"] = entity_types
            return module
    module = {
        "name": domain,
        "entity_types": [entity_type] if entity_type else [],
        "gate_properties": [],
        "category_gate_labels": [],
        "indicator_terms": [],
        "relation_properties": {},
    }
    modules.append(module)
    return module


def _change_pid(change: Change) -> str | None:
    for evidence in change.evidence:
        detail = evidence.detail
        pid = detail.split("/", 1)[0].strip()
        if pid.startswith("P"):
            return pid
    if change.value and change.value.startswith("P"):
        return change.value
    return None


def _is_relation_change(change: Change) -> bool:
    return change.action == "add_relation_type" or change.target_type in {"entity", "relational"}


def _schema_type_name(change: Change, default_entity_type: str) -> str:
    if _is_relation_change(change):
        if change.target_type and change.target_type not in {"entity", "relational"}:
            return change.target_type
        return change.target_type if change.target_type and change.target_type[:1].isupper() else default_entity_type
    if change.target_type == "date":
        return "STD.Date"
    return "Text"


def _default_module_name(section: str) -> str:
    return "common_properties" if section == "property" else "common_relations"


def _field_display_label(change: Change, field_name: str) -> str:
    candidate = change.value or field_name
    if candidate == field_name or candidate.islower():
        return _humanize_field_name(field_name)
    return candidate[:1].upper() + candidate[1:]


def _humanize_field_name(text: str) -> str:
    words: list[str] = []
    current = []
    for index, ch in enumerate(text):
        if ch == "_":
            if current:
                words.append("".join(current))
                current = []
            continue
        if ch.isupper() and current and (text[index - 1].islower() or (index + 1 < len(text) and text[index + 1].islower())):
            words.append("".join(current))
            current = [ch.lower()]
            continue
        current.append(ch.lower())
    if current:
        words.append("".join(current))
    if not words:
        return text
    words[0] = words[0][:1].upper() + words[0][1:]
    return " ".join(words)


def _camel_case_fallback(text: str) -> str:
    parts = [part for part in "".join(ch if ch.isalnum() else " " for ch in text).split() if part]
    if not parts:
        return "field"
    return parts[0].lower() + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _pascal_case(text: str) -> str:
    parts = [part for part in "".join(ch if ch.isalnum() else " " for ch in text).split() if part]
    if not parts:
        return "Thing"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _group_entities_by_domain(schema_doc: SchemaDocument, domain_order: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {domain: [] for domain in domain_order}
    for entity_name, entity in schema_doc.entities.items():
        if entity.domain in grouped:
            grouped[entity.domain].append(entity_name)
    return grouped


def _render_entity(entity: EntityType) -> list[str]:
    lines = [f"{entity.name}({entity.label}): {entity.kind}"]
    property_fields = [field for field in entity.fields if field.section == "property"]
    relation_fields = [field for field in entity.fields if field.section == "relation"]
    if property_fields:
        lines.append("  properties:")
        lines.extend(_render_field_group(property_fields))
    if relation_fields:
        lines.append("  relations:")
        lines.extend(_render_field_group(relation_fields))
    return lines


def _render_field_group(fields: list[SchemaField]) -> list[str]:
    lines: list[str] = []
    current_module: str | None = None
    for field in fields:
        if field.module != current_module and field.module:
            lines.append(f"    #modules: {field.module}")
            current_module = field.module
        lines.append(f"    {field.name}({field.label}): {field.type_name}")
        for constraint in field.constraints:
            lines.append(f"      constraint: {constraint}")
    return lines
