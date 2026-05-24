from __future__ import annotations

import argparse
import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import requests


SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"
ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

CATEGORY_QUERIES = {
    "industry": """
SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {
  ?item wdt:P31/wdt:P279* wd:Q8148.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT {limit}
""",
    "product": """
SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {
  ?item wdt:P31/wdt:P279* wd:Q2424752.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT {limit}
""",
    "enterprise": """
SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {
  ?item wdt:P31/wdt:P279* wd:Q4830453.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT {limit}
""",
    "technology": """
SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {
  VALUES ?root { wd:Q11016 wd:Q2695280 wd:Q253623 }
  ?item wdt:P31/wdt:P279* ?root.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT {limit}
""",
}

DEFAULT_PROPERTIES = (
    "P31",
    "P279",
    "P452",
    "P176",
    "P186",
    "P527",
    "P856",
    "P571",
    "P127",
    "P355",
    "P178",
    "P577",
    "P131",
)

SEARCH_TERMS = {
    "industry": (
        "automotive industry",
        "semiconductor industry",
        "chemical industry",
        "pharmaceutical industry",
        "textile industry",
        "aerospace industry",
        "steel industry",
        "mining industry",
        "construction industry",
        "tourism industry",
        "video game industry",
        "film industry",
        "music industry",
        "food industry",
        "petroleum industry",
        "shipbuilding industry",
        "telecommunications industry",
        "renewable energy industry",
        "electronics industry",
        "retail",
        "banking industry",
        "insurance industry",
        "rail transport",
        "fashion industry",
        "paper industry",
    ),
    "product": (
        "lithium-ion battery",
        "silicon wafer",
        "electric vehicle",
        "smartphone",
        "solar panel",
        "microprocessor",
        "integrated circuit",
        "OLED display",
        "wind turbine",
        "electric motor",
        "LED lamp",
        "aircraft engine",
        "semiconductor device",
        "printed circuit board",
        "insulin pump",
        "medical device",
        "laptop",
        "tablet computer",
        "server",
        "router",
        "3D printer",
        "industrial robot",
        "battery electric bus",
        "memory card",
        "hard disk drive",
    ),
    "enterprise": (
        "Tesla, Inc.",
        "Apple Inc.",
        "Samsung Electronics",
        "Taiwan Semiconductor Manufacturing Company",
        "Intel",
        "Toyota",
        "Volkswagen Group",
        "Microsoft",
        "Amazon",
        "Alphabet Inc.",
        "Nvidia",
        "Sony",
        "Panasonic",
        "BYD Company",
        "Huawei",
        "Siemens",
        "General Electric",
        "Boeing",
        "Airbus",
        "Pfizer",
        "Roche",
        "BASF",
        "Shell plc",
        "ExxonMobil",
        "IBM",
    ),
    "technology": (
        "photolithography",
        "extreme ultraviolet lithography",
        "machine learning",
        "artificial intelligence",
        "blockchain",
        "5G",
        "cloud computing",
        "quantum computing",
        "additive manufacturing",
        "CRISPR",
        "gene therapy",
        "mRNA vaccine",
        "solar cell",
        "wind power",
        "hydrogen fuel cell",
        "carbon capture and storage",
        "robotics",
        "autonomous vehicle",
        "natural language processing",
        "computer vision",
        "Internet of things",
        "virtual reality",
        "augmented reality",
        "nanotechnology",
        "biotechnology",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("examples/wikidata_validation_100.json"))
    parser.add_argument("--per-category", type=int, default=25)
    parser.add_argument("--source", choices=("titles", "search", "sparql"), default="titles")
    parser.add_argument("--sleep", type=float, default=0.6)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "wikidata-ontology-expander/0.1 validation fixture fetcher",
        }
    )

    selected: OrderedDict[str, dict[str, Any]] = OrderedDict()
    if args.source == "titles":
        selected.update(fetch_title_selection(session, args.per_category, args.timeout))
        print(f"titles: selected {len(selected)} entities", flush=True)
    elif args.source == "sparql":
        for category, query_template in CATEGORY_QUERIES.items():
            rows = run_sparql(session, query_template.replace("{limit}", str(args.per_category)), args.timeout)
            for row in rows:
                qid = row["item"]["value"].rsplit("/", 1)[-1]
                if qid not in selected:
                    selected[qid] = {
                        "category": category,
                        "qid": qid,
                        "label": row.get("itemLabel", {}).get("value", qid),
                        "description": row.get("itemDescription", {}).get("value", ""),
                    }
            print(f"{category}: selected {len(rows)} rows")
    else:
        for category, terms in SEARCH_TERMS.items():
            count = 0
            for term in terms[: args.per_category]:
                try:
                    hit = search_top_entity(session, term, args.timeout)
                except requests.RequestException as exc:
                    print(f"{category}: skipped search term {term!r}: {exc}", flush=True)
                    continue
                if hit and hit["qid"] not in selected:
                    selected[hit["qid"]] = {"category": category, **hit}
                    count += 1
                time.sleep(args.sleep)
            print(f"{category}: selected {count} search hits", flush=True)

    raw_entities = fetch_entities_batch(session, tuple(selected), DEFAULT_PROPERTIES, args.timeout)
    entities = []
    search: dict[str, list[str]] = {}
    for index, item in enumerate(selected.values(), start=1):
        entity = raw_entities.get(item["qid"])
        if entity is None:
            print(f"{index:03d}/{len(selected)} skipped missing entity {item['qid']}", flush=True)
            continue
        entity["expected_category"] = item["category"]
        entities.append(entity)
        add_search_terms(search, entity)
        print(f"{index:03d}/{len(selected)} {entity['qid']} {entity['label']}", flush=True)

    payload = {
        "metadata": {
            "source": "wikidata",
            "entity_count": len(entities),
            "properties": list(DEFAULT_PROPERTIES),
            "categories": {name: args.per_category for name in CATEGORY_QUERIES},
        },
        "search": search,
        "entities": entities,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(entities)} entities to {args.output}")


def run_sparql(session: requests.Session, query: str, timeout: int) -> list[dict[str, Any]]:
    response = get_with_retry(
        session,
        SPARQL_URL,
        params={"query": query, "format": "json"},
        timeout=timeout,
    )
    return response.json()["results"]["bindings"]


def fetch_title_selection(
    session: requests.Session,
    per_category: int,
    timeout: int,
) -> OrderedDict[str, dict[str, str]]:
    title_to_category: OrderedDict[str, str] = OrderedDict()
    normalized_title_to_category: dict[str, str] = {}
    for category, terms in SEARCH_TERMS.items():
        for title in terms[:per_category]:
            title_to_category[title] = category
            normalized_title_to_category[title.lower()] = category

    selected: OrderedDict[str, dict[str, str]] = OrderedDict()
    titles = tuple(title_to_category)
    for start in range(0, len(titles), 10):
        batch = titles[start : start + 10]
        response = get_with_retry(
            session,
            API_URL,
            params={
                "action": "wbgetentities",
                "format": "json",
                "sites": "enwiki",
                "titles": "|".join(batch),
                "languages": "en",
                "props": "labels|descriptions|sitelinks",
            },
            timeout=timeout,
        )
        entities = response.json().get("entities", {})
        for entity in entities.values():
            if entity.get("missing"):
                continue
            title = entity.get("sitelinks", {}).get("enwiki", {}).get("title")
            qid = entity.get("id")
            if not title or not qid:
                continue
            category = title_to_category.get(title) or normalized_title_to_category.get(title.lower())
            if category and qid not in selected:
                selected[qid] = {
                    "category": category,
                    "qid": qid,
                    "label": localized_value(entity.get("labels", {}), "en", qid),
                    "description": localized_value(entity.get("descriptions", {}), "en", ""),
                }
        time.sleep(1.0)
    return selected


def search_top_entity(session: requests.Session, term: str, timeout: int) -> dict[str, str] | None:
    response = get_with_retry(
        session,
        API_URL,
        params={
            "action": "wbsearchentities",
            "format": "json",
            "language": "en",
            "uselang": "en",
            "search": term,
            "limit": 1,
        },
        timeout=timeout,
    )
    rows = response.json().get("search", [])
    if not rows:
        return None
    row = rows[0]
    return {
        "qid": row["id"],
        "label": row.get("label", row["id"]),
        "description": row.get("description", ""),
    }


def fetch_entity(
    session: requests.Session,
    qid: str,
    properties: tuple[str, ...],
    timeout: int,
) -> dict[str, Any]:
    response = get_with_retry(session, ENTITY_URL.format(qid=qid), timeout=timeout)
    data = response.json()["entities"][qid]
    aliases = [item["value"] for item in data.get("aliases", {}).get("en", [])[:8]]
    statements = []
    for pid in properties:
        for claim in data.get("claims", {}).get(pid, [])[:10]:
            statement = claim_to_statement(pid, claim)
            if statement is not None:
                statements.append(statement)
    return {
        "qid": qid,
        "label": localized_value(data.get("labels", {}), "en", qid),
        "description": localized_value(data.get("descriptions", {}), "en", ""),
        "aliases": aliases,
        "statements": statements,
        "url": f"https://www.wikidata.org/wiki/{qid}",
    }


def fetch_entities_batch(
    session: requests.Session,
    qids: tuple[str, ...],
    properties: tuple[str, ...],
    timeout: int,
) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for start in range(0, len(qids), 10):
        batch = qids[start : start + 10]
        response = get_with_retry(
            session,
            API_URL,
            params={
                "action": "wbgetentities",
                "format": "json",
                "languages": "en",
                "props": "labels|descriptions|aliases|claims",
                "ids": "|".join(batch),
            },
            timeout=timeout,
        )
        data = response.json().get("entities", {})
        for qid, item in data.items():
            if item.get("missing"):
                continue
            aliases = [alias["value"] for alias in item.get("aliases", {}).get("en", [])[:8]]
            statements = []
            for pid in properties:
                for claim in item.get("claims", {}).get(pid, [])[:10]:
                    statement = claim_to_statement(pid, claim)
                    if statement is not None:
                        statements.append(statement)
            entities[qid] = {
                "qid": qid,
                "label": localized_value(item.get("labels", {}), "en", qid),
                "description": localized_value(item.get("descriptions", {}), "en", ""),
                "aliases": aliases,
                "statements": statements,
                "url": f"https://www.wikidata.org/wiki/{qid}",
            }
        time.sleep(1.0)
    return entities


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int,
    attempts: int = 5,
) -> requests.Response:
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException:
            if attempt == attempts:
                raise
            time.sleep(delay)
            delay *= 1.8
            continue
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt == attempts:
            response.raise_for_status()
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        time.sleep(delay)
        delay *= 1.8
    raise RuntimeError("unreachable retry state")


def localized_value(values: dict[str, Any], language: str, default: str) -> str:
    if language in values:
        return values[language].get("value", default)
    if values:
        return next(iter(values.values())).get("value", default)
    return default


def claim_to_statement(pid: str, claim: dict[str, Any]) -> dict[str, Any] | None:
    datavalue = claim.get("mainsnak", {}).get("datavalue")
    if not datavalue:
        return None
    raw_value = datavalue.get("value")
    value_id = None
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
    return {
        "property_id": pid,
        "property_label": pid,
        "value_id": value_id,
        "value_label": value_label,
        "raw_value": raw_value,
    }


def add_search_terms(search: dict[str, list[str]], entity: dict[str, Any]) -> None:
    terms = [entity["label"], *entity.get("aliases", [])[:3]]
    for term in terms:
        normalized = term.strip().lower()
        if normalized:
            search.setdefault(normalized, []).append(entity["qid"])


if __name__ == "__main__":
    main()
