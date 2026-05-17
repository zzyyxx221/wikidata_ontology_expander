from __future__ import annotations

import json
from pathlib import Path

from .models import WikidataEntity, WikidataStatement


class FixtureWikidataClient:
    """Small offline Wikidata-like client for network-restricted servers."""

    def __init__(self, fixture_path: Path):
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.search_index = {
            key.lower(): value for key, value in data.get("search", {}).items()
        }
        self.entities = {
            item["qid"]: _entity_from_dict(item)
            for item in data.get("entities", [])
        }

    def search(self, term: str, limit: int = 5) -> list[WikidataEntity]:
        qids = self.search_index.get(term.lower(), [])
        return [self.entities[qid] for qid in qids[:limit] if qid in self.entities]

    def get_entity(self, qid: str, properties=None) -> WikidataEntity:
        entity = self.entities[qid]
        if not properties:
            return entity
        allowed = set(properties)
        return WikidataEntity(
            qid=entity.qid,
            label=entity.label,
            description=entity.description,
            aliases=entity.aliases,
            statements=tuple(s for s in entity.statements if s.property_id in allowed),
            url=entity.url,
        )


def _entity_from_dict(item: dict) -> WikidataEntity:
    return WikidataEntity(
        qid=item["qid"],
        label=item["label"],
        description=item.get("description", ""),
        aliases=tuple(item.get("aliases", [])),
        statements=tuple(
            WikidataStatement(
                property_id=statement["property_id"],
                property_label=statement.get("property_label", statement["property_id"]),
                value_id=statement.get("value_id"),
                value_label=statement.get("value_label", ""),
                raw_value=statement.get("raw_value"),
            )
            for statement in item.get("statements", [])
        ),
        url=item.get("url") or f"https://www.wikidata.org/wiki/{item['qid']}",
    )
