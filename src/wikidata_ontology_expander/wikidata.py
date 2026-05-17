from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import requests

from .models import WikidataEntity, WikidataStatement


class WikidataClient:
    API_URL = "https://www.wikidata.org/w/api.php"
    ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

    def __init__(self, language: str = "en", timeout: int = 20, user_agent: str | None = None):
        self.language = language
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent
                or "wikidata-ontology-expander/0.1 (ontology expansion research)"
            }
        )

    def search(self, term: str, limit: int = 5) -> list[WikidataEntity]:
        params = {
            "action": "wbsearchentities",
            "format": "json",
            "language": self.language,
            "uselang": self.language,
            "search": term,
            "limit": limit,
        }
        response = self.session.get(self.API_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        entities = []
        for item in response.json().get("search", []):
            qid = item["id"]
            entities.append(
                WikidataEntity(
                    qid=qid,
                    label=item.get("label", qid),
                    description=item.get("description", ""),
                    aliases=tuple(item.get("aliases", [])),
                    url=item.get("concepturi"),
                )
            )
        return entities

    def get_entity(self, qid: str, properties: Iterable[str] | None = None) -> WikidataEntity:
        response = self.session.get(self.ENTITY_URL.format(qid=qid), timeout=self.timeout)
        response.raise_for_status()
        entity = response.json()["entities"][qid]
        labels = entity.get("labels", {})
        descriptions = entity.get("descriptions", {})
        aliases = entity.get("aliases", {})
        prop_filter = set(properties or [])

        statements: list[WikidataStatement] = []
        for pid, claims in entity.get("claims", {}).items():
            if prop_filter and pid not in prop_filter:
                continue
            for claim in claims:
                statement = _claim_to_statement(pid, claim, self.language)
                if statement:
                    statements.append(statement)

        return WikidataEntity(
            qid=qid,
            label=_localized_value(labels, self.language, qid),
            description=_localized_value(descriptions, self.language, ""),
            aliases=tuple(a["value"] for a in aliases.get(self.language, [])),
            statements=tuple(statements),
            url=f"https://www.wikidata.org/wiki/{qid}",
        )


def _localized_value(values: dict[str, Any], language: str, default: str) -> str:
    if language in values:
        return values[language].get("value", default)
    if "en" in values:
        return values["en"].get("value", default)
    if values:
        first = next(iter(values.values()))
        return first.get("value", default)
    return default


def _claim_to_statement(pid: str, claim: dict[str, Any], language: str) -> WikidataStatement | None:
    mainsnak = claim.get("mainsnak", {})
    datavalue = mainsnak.get("datavalue")
    if not datavalue:
        return None
    raw_value = datavalue.get("value")
    value_id = None
    value_label = ""
    if isinstance(raw_value, dict):
        if raw_value.get("entity-type") == "item":
            value_id = f"Q{raw_value.get('numeric-id')}"
            value_label = value_id
        elif "time" in raw_value:
            value_label = raw_value["time"]
        elif "text" in raw_value:
            value_label = raw_value["text"]
        elif "amount" in raw_value:
            value_label = raw_value["amount"]
        else:
            value_label = str(raw_value)
    else:
        value_label = str(raw_value)
    return WikidataStatement(
        property_id=pid,
        property_label=pid,
        value_id=value_id,
        value_label=value_label,
        raw_value=raw_value,
    )

