from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Evidence, WikidataEntity


@dataclass(frozen=True)
class TaxonomyNode:
    code: str
    label: str
    entity_type: str
    domain: str
    level: int | None = None
    parent_code: str | None = None
    source_sheet: str | None = None
    is_leaf: bool = False


@dataclass(frozen=True)
class TaxonomyMatch:
    node: TaxonomyNode
    score: float
    evidence: Evidence


class TaxonomyReference:
    """Reference taxonomy loaded from the industry/product Excel workbook."""

    def __init__(self, nodes: tuple[TaxonomyNode, ...]):
        self.nodes = nodes
        self._terms: list[tuple[str, TaxonomyNode]] = []
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            for term in _term_variants(node.label, node.code):
                key = (term, node.code)
                if key not in seen:
                    seen.add(key)
                    self._terms.append((term, node))
        self._terms.sort(key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def load(cls, path: Path) -> "TaxonomyReference":
        if path.suffix.lower() == ".xlsx":
            return cls(load_excel_taxonomy(path))
        raise ValueError(f"unsupported taxonomy reference format: {path.suffix}")

    def best_match(self, candidate: WikidataEntity) -> TaxonomyMatch | None:
        haystack = _normalized_text(
            " ".join(
                (
                    candidate.label,
                    candidate.description,
                    " ".join(candidate.aliases),
                    " ".join(statement.value_label for statement in candidate.statements),
                )
            )
        )
        if not haystack:
            return None
        for term, node in self._terms:
            if _contains_term(haystack, term):
                score = 0.26 if _normalized_text(candidate.label) == term else 0.18
                return TaxonomyMatch(
                    node=node,
                    score=score,
                    evidence=Evidence(
                        "taxonomy_reference",
                        _taxonomy_evidence_detail(node),
                        score,
                    ),
                )
        return None


def load_excel_taxonomy(path: Path) -> tuple[TaxonomyNode, ...]:
    workbook = _XlsxWorkbook(path)
    nodes: dict[tuple[str, str], TaxonomyNode] = {}
    if "行业分类" in workbook.sheet_names:
        _load_industry_sheet(workbook, nodes)
    if "行业+产品" in workbook.sheet_names:
        _load_product_sheet(workbook, nodes)
    return _mark_leaf_nodes(tuple(nodes.values()))


def _mark_leaf_nodes(nodes: tuple[TaxonomyNode, ...]) -> tuple[TaxonomyNode, ...]:
    parent_codes = {node.parent_code for node in nodes if node.parent_code}
    return tuple(replace(node, is_leaf=node.code not in parent_codes) for node in nodes)


def _taxonomy_evidence_detail(node: TaxonomyNode) -> str:
    level = f", level={node.level}" if node.level is not None else ""
    parent = f", parent={node.parent_code}" if node.parent_code else ""
    leaf = ", leaf" if node.is_leaf else ", non-leaf"
    return f"matched {node.domain}/{node.entity_type} taxonomy node {node.code}: {node.label}{level}{parent}{leaf}"


def _load_industry_sheet(workbook: "_XlsxWorkbook", nodes: dict[tuple[str, str], TaxonomyNode]) -> None:
    for row in workbook.rows("行业分类"):
        if not row or row[0] == "Sector id":
            continue
        sector_code, sector_name = _cell(row, 0), _cell(row, 1)
        group_code, group_name = _cell(row, 2), _cell(row, 3)
        industry_code, industry_name = _cell(row, 4), _cell(row, 5)
        sub_code, sub_name = _cell(row, 6), _cell(row, 7)
        if sector_code and sector_name:
            _put_node(nodes, TaxonomyNode(sector_code, sector_name, "EconomicSector", "industry", 1, None, "行业分类"))
        if group_code and group_name:
            _put_node(nodes, TaxonomyNode(group_code, group_name, "IndustryGroup", "industry", 2, sector_code, "行业分类"))
        if industry_code and industry_name:
            _put_node(nodes, TaxonomyNode(industry_code, industry_name, "Industry", "industry", 3, group_code, "行业分类"))
        if sub_code and sub_name:
            _put_node(nodes, TaxonomyNode(sub_code, sub_name, "Industry", "industry", 4, industry_code, "行业分类"))


def _load_product_sheet(workbook: "_XlsxWorkbook", nodes: dict[tuple[str, str], TaxonomyNode]) -> None:
    for row in workbook.rows("行业+产品"):
        if not row or row[0] == "Sub-Industry id":
            continue
        parent_code = _cell(row, 0)
        for base in range(2, len(row), 3):
            code = _cell(row, base)
            level = _cell(row, base + 1)
            label = _cell(row, base + 2)
            if not code or not label:
                continue
            level_num = _int_or_none(level)
            _put_node(nodes, TaxonomyNode(code, label, "Product", "product", level_num, parent_code, "行业+产品"))
            parent_code = code


def _put_node(nodes: dict[tuple[str, str], TaxonomyNode], node: TaxonomyNode) -> None:
    nodes.setdefault((node.domain, node.code), node)


def _cell(row: list[str], index: int) -> str | None:
    if index >= len(row):
        return None
    value = row[index]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _term_variants(label: str, code: str) -> tuple[str, ...]:
    variants = [_normalized_text(label), _normalized_text(code)]
    return tuple(item for item in variants if item)


def _normalized_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _contains_term(haystack: str, term: str) -> bool:
    if not term:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in term):
        return term in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None


class _XlsxWorkbook:
    NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    NS_PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    def __init__(self, path: Path):
        self.path = path
        self.archive = zipfile.ZipFile(path)
        self.shared_strings = self._load_shared_strings()
        self._sheet_paths = self._load_sheet_paths()

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return tuple(self._sheet_paths)

    def rows(self, sheet_name: str) -> list[list[str]]:
        sheet_path = self._sheet_paths[sheet_name]
        root = ET.fromstring(self.archive.read(sheet_path))
        rows: list[list[str]] = []
        for row in root.iter(f"{self.NS_MAIN}row"):
            values: list[str] = []
            for cell in row.findall(f"{self.NS_MAIN}c"):
                index = _column_index(cell.attrib.get("r", ""))
                while len(values) < index:
                    values.append("")
                values.append(self._cell_value(cell))
            rows.append(values)
        return rows

    def _load_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self.archive.namelist():
            return []
        root = ET.fromstring(self.archive.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in root.findall(f"{self.NS_MAIN}si"):
            parts = [node.text or "" for node in item.iter(f"{self.NS_MAIN}t")]
            strings.append("".join(parts))
        return strings

    def _load_sheet_paths(self) -> dict[str, str]:
        workbook_root = ET.fromstring(self.archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall(f"{self.NS_PACKAGE_REL}Relationship")
        }
        sheet_paths: dict[str, str] = {}
        for sheet in workbook_root.iter(f"{self.NS_MAIN}sheet"):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib[f"{self.NS_REL}id"]
            target = rel_targets[rel_id]
            sheet_paths[name] = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        return sheet_paths

    def _cell_value(self, cell: ET.Element) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.iter(f"{self.NS_MAIN}t"))
        value = cell.find(f"{self.NS_MAIN}v")
        if value is None or value.text is None:
            return ""
        if cell_type == "s":
            index = int(value.text)
            return self.shared_strings[index] if index < len(self.shared_strings) else ""
        return value.text


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    if not letters:
        return 0
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - ord("A") + 1)
    return index - 1
