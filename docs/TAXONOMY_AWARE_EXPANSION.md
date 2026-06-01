# Taxonomy-aware schema expansion 技术说明

## 1. 背景

当前项目的扩充目标从“自由扩充 ontology 顶层结构”调整为：

```text
固定 schema 顶层 domain / entity type
参考 Excel 中已有的产业与产品分类体系
继续扩充分类入口规则、模块、属性槽位和关系槽位
```

这里的 Excel 指 `/Users/zyx/Desktop/工作组会/行业分类+产品(1).xlsx` 这一类行业与产品分类表。它提供的是分类参照系，而不是新的顶层 schema 定义。

## 2. 设计原则

### 2.1 顶层 schema 冻结

顶层结构不再自动扩充，主要包括：

- domain 不新增，例如不新增新的“产业域 / 产品域 / 技术域”之外的顶层域。
- entity type 不新增，例如不把叶子产品、子行业或 Wikidata 概念提升为新的 `ConceptType`。
- `add_concept` 在默认示例配置中被禁用。

### 2.2 仍然允许 schema 能力扩充

以下 action 仍然是合理且默认允许的：

- `add_category_gate`
- `add_module`
- `add_property_type`
- `add_relation_type`

它们的定位如下：

| Action | 含义 | 是否改变顶层 schema |
| --- | --- | --- |
| `add_category_gate` | 扩充分流 / 分类入口规则，让更多候选能进入已有 domain | 否 |
| `add_module` | 在已有 domain/entity 下增加模块容器 | 否 |
| `add_property_type` | 给已有 entity type 增加属性槽位 | 否 |
| `add_relation_type` | 给已有 entity type 增加关系槽位 | 否 |
| `add_concept` | 新增概念类型 | 是，默认禁用 |

### 2.3 Excel taxonomy 作为参照系

Excel taxonomy 用来提供分类上下文：

- `行业分类` sheet 解析为产业域节点：
  - `EconomicSector`
  - `IndustryGroup`
  - `Industry`
  - 子行业也暂以 `Industry` 节点处理，层级为 4
- `行业+产品` sheet 解析为产品域节点：
  - 所有产品层级都挂在 `Product`
  - 产品 level 来自 Excel 的 `level`
  - 相邻 code 构成父子关系
  - 自动标记叶子节点 `is_leaf`

Excel 不是直接生成 `add_concept`，而是帮助判断候选实体是否处在已有行业/产品分类上下文中。

## 3. 代码改动概览

### 3.1 `models.py`

文件：

```text
src/wikidata_ontology_expander/models.py
```

`ExpansionConfig` 新增字段：

```python
freeze_top_level_schema: bool = False
allowed_schema_actions: tuple[str, ...] = ()
restricted_schema_actions: tuple[str, ...] = ()
require_taxonomy_context: bool = False
taxonomy_context_domains: tuple[str, ...] = ("industry", "product")
prefer_leaf_taxonomy_evidence: bool = False
```

字段含义：

- `freeze_top_level_schema`
  - 冻结顶层 schema。
  - 当前实现中主要用于禁止 `add_concept`。
- `allowed_schema_actions`
  - action 白名单。
  - 非空时，只有列出的 action 能输出。
- `restricted_schema_actions`
  - action 黑名单。
  - 优先级高于白名单。
- `require_taxonomy_context`
  - 对 `taxonomy_context_domains` 中的 domain，要求候选必须命中 Excel taxonomy 才能产生 schema proposal。
- `taxonomy_context_domains`
  - 需要 taxonomy 约束的 domain，默认是 `industry` 和 `product`。
- `prefer_leaf_taxonomy_evidence`
  - 对需要 taxonomy 约束的 domain，只让 Excel 叶子节点候选产生 schema proposal。

### 3.2 `taxonomy.py`

文件：

```text
src/wikidata_ontology_expander/taxonomy.py
```

主要能力：

- 加载 `.xlsx` taxonomy。
- 解析 `行业分类` 与 `行业+产品` 两个 sheet。
- 构造 `TaxonomyNode`。
- 自动计算 `is_leaf`。
- 通过 `TaxonomyReference.best_match(candidate)` 为 Wikidata 候选提供 taxonomy evidence。

`TaxonomyNode` 现在包含：

```python
code: str
label: str
entity_type: str
domain: str
level: int | None
parent_code: str | None
source_sheet: str | None
is_leaf: bool
```

taxonomy evidence 会记录：

```text
matched product/Product taxonomy node EC001...: 镍钴锰酸锂, level=9, parent=..., leaf
```

### 3.3 `engine.py`

文件：

```text
src/wikidata_ontology_expander/engine.py
```

核心调整：

1. 候选实体先经过原有 `GatePolicy` 分类。
2. 如果提供了 `taxonomy_reference`，则尝试匹配 Excel taxonomy。
3. taxonomy match 会增强候选的 category score，并加入 evidence。
4. 在产生 proposal 前，根据配置判断是否允许输出：
   - 是否在 action 白名单中。
   - 是否被 action 黑名单禁止。
   - 是否需要 taxonomy context。
   - 是否需要叶子节点 evidence。
5. `freeze_top_level_schema=true` 时只禁止 `add_concept`，不禁止 `add_category_gate`。

当前逻辑：

```text
freeze_top_level_schema=true
  -> 禁止 add_concept
  -> 允许 add_category_gate
  -> 允许 add_module
  -> 允许 add_property_type
  -> 允许 add_relation_type
```

此外修复了一个实体类型推断问题：

- 之前 `term` 会误命中 `terminal`，导致部分产品被误判为 `ProductTerm`。
- 现在英文单词关键词使用词边界匹配。

### 3.4 `cli.py`

文件：

```text
src/wikidata_ontology_expander/cli.py
```

`expand` 和 `expand-corpus` 已支持：

```bash
--taxonomy-excel /path/to/行业分类+产品.xlsx
```

传入后会加载 `TaxonomyReference`，参与候选分类和 proposal 约束。

## 4. 配置说明

示例配置：

```json
{
  "proposal_policy": {
    "freeze_top_level_schema": true,
    "allowed_schema_actions": [
      "add_category_gate",
      "add_module",
      "add_property_type",
      "add_relation_type"
    ],
    "restricted_schema_actions": [
      "add_concept"
    ],
    "require_taxonomy_context": false,
    "taxonomy_context_domains": [
      "industry",
      "product"
    ],
    "prefer_leaf_taxonomy_evidence": false
  }
}
```

默认示例配置位于：

```text
examples/config.json
```

### 4.1 宽松模式

适合没有 Excel 或希望充分发现 proposal 的情况：

```json
{
  "require_taxonomy_context": false,
  "prefer_leaf_taxonomy_evidence": false
}
```

效果：

- Excel taxonomy 只作为加分 evidence。
- 未命中 Excel 的候选仍可产生 `add_module / add_property_type / add_relation_type`。

### 4.2 严格 taxonomy 模式

适合希望扩充严格受 Excel 分类体系约束的情况：

```json
{
  "require_taxonomy_context": true,
  "prefer_leaf_taxonomy_evidence": true
}
```

效果：

- `industry` / `product` domain 的候选必须命中 Excel taxonomy。
- 如果开启叶子偏好，则只有 Excel 叶子节点候选产生 schema proposal。
- 其他 domain，例如 `enterprise`、`technology`，不受这个限制。

## 5. 离线 fixture

新增 fixture：

```text
examples/offline_wikidata_fixture_taxonomy.json
```

该 fixture 用于验证 taxonomy-aware expansion 场景，包含：

- `镍钴锰酸锂`
- `功率放大器芯片`
- `晶圆检测设备`
- `生物医药研发服务`
- `新能源汽车零部件`
- `固态电池`
- `碳化硅MOSFET`
- `光刻胶`
- `氢燃料电池系统`
- `工业机器人`
- `半导体制造行业`
- `药物发现CRO服务`

这些实体会触发如下类型的 schema proposal：

- `add_property_type`
  - `nominalVoltage`
  - `specificCapacity`
  - `processNode`
  - `packageType`
  - `frequencyBand`
  - `inspectionResolution`
  - `waferSize`
  - `applicationVehicleType`
  - `safetyCertification`
  - `energyDensity`
  - `cycleLife`
  - `electrolyteType`
  - `breakdownVoltage`
  - `onResistance`
  - `operatingTemperature`
  - `exposureWavelength`
  - `viscosity`
  - `stackPower`
  - `hydrogenPurityRequirement`
  - `coldStartTemperature`
  - `payloadCapacity`
  - `repeatability`
  - `axisCount`
  - `capitalIntensity`
  - `waferFabType`
  - `processTechnologyGeneration`
  - `assayType`
  - `deliveryModel`
- `add_relation_type`
  - `manufacturer`
  - `developer`

如果候选无法进入已有 category，但其 `P31 / P279` 类型明显指向某个已有 domain，则仍可触发：

- `add_category_gate`

## 6. 运行示例

### 6.1 不传 Excel，仅使用离线 fixture

```bash
PYTHONPATH=src python3 -m wikidata_ontology_expander.cli expand-corpus \
  --schema data/IncCoreV2.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture_taxonomy.json \
  --output out/taxonomy_fixture_changeset.json
```

### 6.2 传入 Excel taxonomy

```bash
PYTHONPATH=src python3 -m wikidata_ontology_expander.cli expand-corpus \
  --schema data/IncCoreV2.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture_taxonomy.json \
  --taxonomy-excel "/Users/zyx/Desktop/工作组会/行业分类+产品(1).xlsx" \
  --output out/taxonomy_fixture_changeset.json
```

传入 Excel 后，命中的候选会在 evidence 中带上 taxonomy 信息。

## 7. 输出解释

输出仍然是标准 `ChangeSet` JSON。

示例：

```json
{
  "action": "add_property_type",
  "entity_type": "Product",
  "label": "Product",
  "domain": "product",
  "module": "upstream_downstream_relations",
  "field": "nominalVoltage",
  "value": "nominal voltage",
  "target_type": "text",
  "support": 1,
  "source_entity_ids": ["QTX001"]
}
```

含义：

- 不新增 `Product` 类型。
- 只是在已有 `Product` entity type 下建议新增 `nominalVoltage` 属性槽位。
- proposal 来源是候选实体 `QTX001`。
- 如果传入 Excel 且命中 taxonomy，evidence 会包含对应 Excel 节点。

## 8. 测试覆盖

相关测试位于：

```text
tests/test_engine.py
```

覆盖内容：

- taxonomy reference 命中后禁止 `add_concept`，但允许 slot proposal。
- 严格 taxonomy 模式下，只允许叶子节点产生产品/行业 proposal。
- `freeze_top_level_schema=true` 时仍允许 `add_category_gate`。
- `proposal_policy` 嵌套配置能正确解析。
- `term` 不再误命中 `terminal`。

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

当前验证结果：

```text
Ran 27 tests
OK
```

## 9. 当前边界

当前改动没有做以下事情：

- 没有把 Excel 产品节点直接导入为实例图谱。
- 没有新增 `SubIndustry` entity type。
- 没有自动把叶子产品变成 `ConceptType`。
- 没有改变 `apply-changes` 的 schema/config 回写基本机制。

因此，本轮改动的核心是：

```text
让 schema proposal engine 参考 Excel taxonomy，
并在冻结顶层 schema 的前提下，
继续发现分类入口规则、模块、属性槽位和关系槽位。
```
