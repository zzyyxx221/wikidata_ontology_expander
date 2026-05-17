from __future__ import annotations

import re
from pathlib import Path

from .models import EntityType, SchemaField


ENTITY_RE = re.compile(r"^([A-Za-z0-9_]+)\((.*?)\):\s*(ConceptType|EntityType|EventType|IndexType)\s*$")
FIELD_RE = re.compile(r"^\s{4}([A-Za-z0-9_]+)\((.*?)\):\s*([A-Za-z0-9_.]+)\s*$")


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def parse_schema(path: Path) -> dict[str, EntityType]:
    return parse_schema_text(read_text(path))


def parse_schema_text(text: str) -> dict[str, EntityType]:
    entities: dict[str, EntityType] = {}
    current_name: str | None = None
    current_label = ""
    current_kind = ""
    current_section: str | None = None
    current_module: str | None = None
    fields: list[SchemaField] = []
    current_field_index: int | None = None

    def flush_current() -> None:
        nonlocal fields
        if current_name:
            entities[current_name] = EntityType(
                name=current_name,
                label=current_label,
                kind=current_kind,
                fields=tuple(fields),
            )
        fields = []

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        entity_match = ENTITY_RE.match(line)
        if entity_match:
            flush_current()
            current_name = entity_match.group(1)
            current_label = entity_match.group(2)
            current_kind = entity_match.group(3)
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
            fields.append(
                SchemaField(
                    owner=current_name,
                    section=current_section,
                    name=field_match.group(1),
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
    return entities

