from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from .models import EntityType, SchemaConceptType, SchemaDocument, SchemaDomain, SchemaField, SchemaModule


ENTITY_RE = re.compile(
    r"^([A-Za-z0-9_]+)\((.*?)\):\s*(ConceptType|EntityType|EventType|IndexType)\s*$"
)
FIELD_RE = re.compile(r"^\s{4}([A-Za-z0-9_]+)\((.*?)\):\s*([A-Za-z0-9_.]+)\s*$")

DOMAIN_ALIASES = {
    "产业域": "industry",
    "产品域": "product",
    "企业域": "enterprise",
    "技术域": "technology",
    "机构域": "organization",
    "人物域": "person",
    "区域域": "region",
    "政策域": "policy",
    "事件域": "event",
    "指标域": "index",
    "文档域": "document",
}


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def schema_cache_path(path: Path, cache_dir: Path | None = None) -> Path:
    root = cache_dir or Path.cwd() / ".wikidata_ontology_cache"
    resolved = str(path.expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return root / f"{path.stem}.{digest}.schema.json"


def load_schema_document(path: Path, cache_dir: Path | None = None, use_cache: bool = True) -> SchemaDocument:
    cache_path = schema_cache_path(path, cache_dir)
    stat = path.stat()
    if use_cache and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            metadata = cached.get("metadata", {})
            if (
                metadata.get("source_path") == str(path.expanduser().resolve())
                and metadata.get("source_mtime_ns") == stat.st_mtime_ns
                and metadata.get("source_size") == stat.st_size
            ):
                return schema_document_from_dict(cached["schema"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass

    doc = parse_schema_document(read_text(path))
    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": {
                "source_path": str(path.expanduser().resolve()),
                "source_mtime_ns": stat.st_mtime_ns,
                "source_size": stat.st_size,
            },
            "schema": schema_document_to_dict(doc),
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def schema_document_to_dict(doc: SchemaDocument) -> dict:
    return asdict(doc)


def schema_document_from_dict(data: dict) -> SchemaDocument:
    entities = {
        name: EntityType(
            name=item["name"],
            label=item["label"],
            kind=item["kind"],
            domain=item.get("domain"),
            fields=tuple(
                SchemaField(
                    owner=field["owner"],
                    section=field["section"],
                    name=field["name"],
                    label=field["label"],
                    type_name=field["type_name"],
                    module=field.get("module"),
                    constraints=tuple(field.get("constraints", ())),
                )
                for field in item.get("fields", ())
            ),
        )
        for name, item in data.get("entities", {}).items()
    }
    return SchemaDocument(
        concept_types=tuple(
            SchemaConceptType(name=item["name"], label=item["label"], kind=item["kind"])
            for item in data.get("concept_types", ())
        ),
        domains=tuple(
            SchemaDomain(
                name=item["name"],
                key=item["key"],
                entity_types=tuple(item.get("entity_types", ())),
            )
            for item in data.get("domains", ())
        ),
        modules=tuple(
            SchemaModule(
                name=item["name"],
                domain=item["domain"],
                kind=item["kind"],
                entity_types=tuple(item.get("entity_types", ())),
                property_fields=tuple(item.get("property_fields", ())),
                relation_fields=tuple(item.get("relation_fields", ())),
            )
            for item in data.get("modules", ())
        ),
        entities=entities,
    )


def normalize_domain_label(label: str) -> str:
    return DOMAIN_ALIASES.get(label, label.strip().lower())


def parse_schema(path: Path) -> dict[str, EntityType]:
    return load_schema_document(path).entities


def parse_schema_text(text: str) -> dict[str, EntityType]:
    return parse_schema_document(text).entities


def parse_schema_document(text: str) -> SchemaDocument:
    concept_types: list[SchemaConceptType] = []
    entities: dict[str, EntityType] = {}
    domain_entity_types: dict[str, list[str]] = {}
    domain_labels: dict[str, str] = {}
    module_entity_types: dict[tuple[str, str], set[str]] = {}
    module_property_fields: dict[tuple[str, str], set[str]] = {}
    module_relation_fields: dict[tuple[str, str], set[str]] = {}

    current_name: str | None = None
    current_label = ""
    current_kind = ""
    current_domain: str | None = None
    current_entity_domain: str | None = None
    current_section: str | None = None
    current_module: str | None = None
    fields: list[SchemaField] = []
    current_field_index: int | None = None

    def flush_current() -> None:
        nonlocal fields
        if not current_name:
            fields = []
            return

        entity = EntityType(
            name=current_name,
            label=current_label,
            kind=current_kind,
            domain=current_entity_domain,
            fields=tuple(fields),
        )
        entities[current_name] = entity
        if entity.kind == "ConceptType":
            concept_types.append(SchemaConceptType(name=entity.name, label=entity.label, kind=entity.kind))
        elif current_entity_domain:
            domain_entity_types.setdefault(current_entity_domain, []).append(entity.name)
        fields = []

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if raw.startswith("#") and not raw.startswith("    #") and not raw.startswith("  #"):
            comment = stripped[1:].strip()
            if (
                comment
                and not comment.startswith("=")
                and not comment.startswith("Schema Naming Conventions")
                and comment.endswith("域")
            ):
                current_domain = normalize_domain_label(comment)
                domain_labels[current_domain] = comment
            continue

        entity_match = ENTITY_RE.match(line)
        if entity_match:
            flush_current()
            current_name = entity_match.group(1)
            current_label = entity_match.group(2)
            current_kind = entity_match.group(3)
            current_entity_domain = current_domain
            current_section = None
            current_module = None
            current_field_index = None
            continue

        if not current_name:
            continue
        if stripped == "properties:":
            current_section = "property"
            current_module = None
            current_field_index = None
            continue
        if stripped == "relations:":
            current_section = "relation"
            current_module = None
            current_field_index = None
            continue
        if stripped.startswith("#modules:"):
            current_module = stripped.split(":", 1)[1].strip()
            current_field_index = None
            continue
        if stripped.startswith("#"):
            continue

        field_match = FIELD_RE.match(line)
        if field_match and current_section:
            field_name = field_match.group(1)
            module_name = current_module or ""
            domain_key = current_entity_domain or ""
            module_key = (domain_key, module_name)
            if module_name:
                module_entity_types.setdefault(module_key, set()).add(current_name)
                if current_section == "property":
                    module_property_fields.setdefault(module_key, set()).add(field_name)
                else:
                    module_relation_fields.setdefault(module_key, set()).add(field_name)
            fields.append(
                SchemaField(
                    owner=current_name,
                    section=current_section,
                    name=field_name,
                    label=field_match.group(2),
                    type_name=field_match.group(3),
                    module=current_module,
                )
            )
            current_field_index = len(fields) - 1
            continue

        if stripped.startswith("constraint:") and current_field_index is not None:
            previous = fields[current_field_index]
            fields[current_field_index] = SchemaField(
                owner=previous.owner,
                section=previous.section,
                name=previous.name,
                label=previous.label,
                type_name=previous.type_name,
                module=previous.module,
                constraints=(*previous.constraints, stripped.split(":", 1)[1].strip()),
            )

    flush_current()

    domains = tuple(
        SchemaDomain(
            name=domain_labels.get(domain_key, domain_key),
            key=domain_key,
            entity_types=tuple(entity_names),
        )
        for domain_key, entity_names in domain_entity_types.items()
    )
    modules = tuple(
        SchemaModule(
            name=module_name,
            domain=domain_key,
            kind=_infer_module_kind(module_name, module_property_fields.get(module_key, set()), module_relation_fields.get(module_key, set())),
            entity_types=tuple(sorted(entity_types)),
            property_fields=tuple(sorted(module_property_fields.get(module_key, set()))),
            relation_fields=tuple(sorted(module_relation_fields.get(module_key, set()))),
        )
        for module_key, entity_types in sorted(module_entity_types.items())
        for domain_key, module_name in (module_key,)
    )
    return SchemaDocument(
        concept_types=tuple(concept_types),
        domains=domains,
        modules=modules,
        entities=entities,
    )


def _infer_module_kind(module_name: str, property_fields: set[str], relation_fields: set[str]) -> str:
    if relation_fields and not property_fields:
        return "relational"
    if property_fields and not relation_fields:
        if module_name.endswith("_relations"):
            return "relational"
        return "intrinsic"
    if relation_fields:
        return "mixed"
    return "intrinsic"
