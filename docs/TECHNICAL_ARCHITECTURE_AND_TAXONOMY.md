# 技术架构与 taxonomy.xlsx 接入说明

## 1. 项目定位

`wikidata_ontology_expander` 是一个面向 ontology/schema 扩充的提案生成项目。它不负责把 Wikidata 或 Excel 中的每一行都导入为实例，也不做实例属性补全；它的核心任务是从外部实体信号中发现 schema 缺口，并输出可审核的 schema-level changeset。

当前默认工作对象是：

- `data/IncCoreV2.schema`：现有本体 schema。
- `examples/config.json`：候选实体路由、属性映射、提案策略配置。
- Wikidata 在线结果或离线 fixture：候选实体与 statement 来源。
- 可选的 `data/taxonomy.xlsx`：行业/产品分类参照表。

项目产出的不是最终 schema，而是一组提案：

- `add_category_gate`：扩充某个 domain 的分类入口规则。
- `add_module`：提示某个 domain/entity 下缺少模块容器。
- `add_property_type`：新增 schema 属性槽位。
- `add_relation_type`：新增 schema 关系槽位。
- `add_concept`：新增 schema 概念/类型。当前配置默认禁止。

## 2. 总体架构

主要代码位于 `src/wikidata_ontology_expander/`：

```text
cli.py              # 命令行入口，负责读取参数并组装 engine
engine.py           # 核心 schema proposal 生成流程
taxonomy.py         # taxonomy.xlsx 读取、节点构造和候选匹配
schema_parser.py    # 解析 .schema 文本为 SchemaDocument
scoring.py          # 候选实体的 domain/module 路由与打分
fixture_client.py   # 离线 Wikidata-like fixture 客户端
wikidata.py         # 在线 Wikidata 客户端
refinement.py       # changeset 回写和多轮迭代
model_review.py     # 可选模型评审层
models.py           # 数据模型
```

主流程如下：

```text
schema + config + candidate corpus
  -> parse schema
  -> load candidates from fixture or Wikidata
  -> classify candidate into domain/module
  -> optionally match taxonomy.xlsx
  -> detect schema gaps
  -> aggregate evidence
  -> generate ChangeSet
  -> optional model review
  -> write JSON output
```

其中 `taxonomy.xlsx` 不替代 schema，也不直接生成实例；它只作为行业/产品分类参照，帮助候选实体进入已有 `industry` / `product` 语义上下文，并按配置约束哪些提案可以输出。

## 3. schema 与 config 的分工

`data/IncCoreV2.schema` 定义本体结构，例如顶层中文 domain、实体类型、属性段、关系段和 `#modules:` 标记。

`examples/config.json` 定义路由和提案策略，例如：

- 每个 domain 对应哪些 `entity_types`。
- 哪些 Wikidata property 可以作为 gate 信号。
- `category_gate_labels`、`indicator_terms` 如何帮助分类。
- `relation_properties` 如何把 relation 字段名映射到 Wikidata PID。
- `proposal_policy` 控制允许输出哪些 schema action。

这个拆分很重要：schema 负责“结构长什么样”，config 负责“候选如何被路由到结构里”。

## 4. taxonomy.xlsx 接入目标

加入 `data/taxonomy.xlsx` 的目的不是把 Excel 里的行业或产品节点全部导入 schema，而是让扩充过程更贴近已有产业/产品分类体系。

接入后会带来三类效果：

1. 候选命中 Excel 节点时，增加 `taxonomy_reference` evidence。
2. 候选原本没有分类时，可以借助 taxonomy 节点补足 `industry` 或 `product` category。
3. 在严格模式下，`industry` / `product` domain 的提案必须命中 taxonomy，甚至可以要求只接受叶子节点。

因此，taxonomy 的角色是“参照系”和“约束信号”，不是新的本体主数据源。

## 5. 文件放置方式

建议把 Excel 放在仓库内：

```text
data/taxonomy.xlsx
```

当前本地仓库中只有 `data/IncCoreV2.schema`，没有 `data/taxonomy.xlsx`。如果服务器上的真实文件在：

```text
/home/zhangyaxin/wikidata_ontology_expander/data/taxonomy.xlsx
```

则命令中直接传这个绝对路径也可以；如果已经进入仓库根目录，更推荐使用相对路径：

```text
data/taxonomy.xlsx
```

## 6. Excel 格式要求

`taxonomy.py` 当前只支持 `.xlsx`，并且按固定 sheet 名读取：

### 6.1 `行业分类` sheet

代码按下面列位读取：

| 列位置 | 含义 |
| --- | --- |
| A | Sector id |
| B | Sector name |
| C | Group id |
| D | Group name |
| E | Industry id |
| F | Industry name |
| G | Sub-Industry id |
| H | Sub-Industry name |

解析结果：

- Sector -> `EconomicSector`，domain 为 `industry`，level 为 1。
- Group -> `IndustryGroup`，domain 为 `industry`，level 为 2。
- Industry -> `Industry`，domain 为 `industry`，level 为 3。
- Sub-Industry -> `Industry`，domain 为 `industry`，level 为 4。

### 6.2 `行业+产品` sheet

代码按下面模式读取：

| 列位置 | 含义 |
| --- | --- |
| A | Sub-Industry id，作为产品链根父节点 |
| C 起每 3 列 | code、level、label，一组表示一层产品节点 |

实际读取规则是从第 C 列开始，每三列为一组：

```text
code, level, label
```

例如：

```text
Sub-Industry id | ... | Product id | level | Product name | Child product id | level | Child product name
```

每个产品节点都会被解析为：

- `entity_type = Product`
- `domain = product`
- `level = Excel 中的 level`
- `parent_code = 上一层 code`
- `source_sheet = 行业+产品`

解析完成后，系统会根据 `parent_code` 自动标记 `is_leaf`。没有子节点的 code 会被视为叶子节点。

## 7. 代码中的接入点

### 7.1 CLI 参数

`expand` 和 `expand-corpus` 都支持：

```bash
--taxonomy-excel data/taxonomy.xlsx
```

在 `cli.py` 中，参数会被加载为：

```python
taxonomy_reference = TaxonomyReference.load(args.taxonomy_excel) if args.taxonomy_excel else None
```

然后传给：

```python
ExpansionEngine(..., taxonomy_reference=taxonomy_reference)
```

### 7.2 Excel 解析

`taxonomy.py` 中的核心对象是：

```python
TaxonomyNode
TaxonomyMatch
TaxonomyReference
```

`TaxonomyReference.load(path)` 只接受 `.xlsx`。内部没有依赖 `openpyxl`，而是直接读取 xlsx zip 包中的 XML，因此 `pyproject.toml` 目前只需要 `requests`。

匹配候选时，系统会把候选的这些文本拼成 haystack：

- label
- description
- aliases
- statement.value_label

然后用 taxonomy 节点的 label/code 做匹配。中文词直接做包含匹配；英文/数字词用词边界匹配，避免 `term` 误命中 `terminal`。

### 7.3 Engine 使用 taxonomy

在 `engine.py` 中，候选先走原有 `GatePolicy.classify()`，再尝试 taxonomy 匹配：

```text
GatePolicy classification
  -> taxonomy best_match
  -> apply taxonomy context
  -> check proposal policy
  -> collect proposal buckets
```

taxonomy match 的影响：

- 如果候选已分类到同一 domain，则增加 category score 和总分。
- 如果候选未分类，则使用 taxonomy 节点的 domain 作为 category。
- evidence 中加入 `taxonomy_reference`。
- 如果命中 taxonomy，默认不再产生 `add_concept`，避免把 Excel 已有分类节点提升为新的 schema 类型。

## 8. 配置策略

`examples/config.json` 当前有：

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
    "restricted_schema_actions": ["add_concept"],
    "require_taxonomy_context": false,
    "taxonomy_context_domains": ["industry", "product"],
    "prefer_leaf_taxonomy_evidence": false
  }
}
```

含义：

- 冻结顶层 schema，不自动新增 `ConceptType`。
- 允许扩充分类入口、模块、属性槽位和关系槽位。
- taxonomy 默认是增强信号，不是硬约束。
- 只有 `industry` 和 `product` 会受 taxonomy 约束配置影响。

### 8.1 宽松模式

适合初期探索：

```json
{
  "require_taxonomy_context": false,
  "prefer_leaf_taxonomy_evidence": false
}
```

效果：

- 命中 taxonomy 的候选会获得额外 evidence。
- 未命中 taxonomy 的候选仍可产生 schema proposal。

### 8.2 严格 taxonomy 模式

适合要求所有行业/产品扩充都落在 Excel 体系内：

```json
{
  "require_taxonomy_context": true,
  "prefer_leaf_taxonomy_evidence": true
}
```

效果：

- `industry` / `product` domain 的提案必须命中 taxonomy。
- 如果开启叶子要求，非叶子 taxonomy 节点不会产生属性/关系槽位提案。
- `enterprise`、`technology` 等其他 domain 不受这个限制。

## 9. 推荐运行命令

在仓库根目录运行。

### 9.1 使用真实 taxonomy.xlsx

```bash
PYTHONPATH=src python3 -m wikidata_ontology_expander.cli expand-corpus \
  --schema data/IncCoreV2.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture_taxonomy.json \
  --taxonomy-excel data/taxonomy.xlsx \
  --output out/taxonomy_fixture_changeset.json
```

如果 Excel 在服务器绝对路径：

```bash
PYTHONPATH=src python3 -m wikidata_ontology_expander.cli expand-corpus \
  --schema data/IncCoreV2.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture_taxonomy.json \
  --taxonomy-excel "/home/zhangyaxin/wikidata_ontology_expander/data/taxonomy.xlsx" \
  --output out/taxonomy_fixture_changeset.json
```

注意：bash 续行符 `\` 后面不能有空格，它必须是该行最后一个字符。

### 9.2 不使用 Excel 的对照运行

```bash
PYTHONPATH=src python3 -m wikidata_ontology_expander.cli expand-corpus \
  --schema data/IncCoreV2.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture_taxonomy.json \
  --output out/taxonomy_fixture_changeset.no_taxonomy.json
```

对比两个输出，可以看 taxonomy evidence 是否进入 changeset。

### 9.3 模型评审注意事项

`examples/config.json` 当前开启了 `model_review.enabled=true`。如果环境里没有 `OPENAI_API_KEY`，命令会报：

```text
missing API key environment variable: OPENAI_API_KEY
```

纯离线测试时可以临时复制一份 config，把：

```json
"model_review": {
  "enabled": false
}
```

或直接删除 `model_review` 配置块。

## 10. 输出检查

运行成功后会生成：

```text
out/taxonomy_fixture_changeset.json
```

重点检查：

### 10.1 refinement_report

```json
"refinement_report": {
  "total_candidates": 5,
  "classified_candidates": 5,
  "unclassified_candidates": 0,
  "module_free_candidates": 2
}
```

这里可以看分类覆盖率、未分类数量和没有命中模块的数量。

### 10.2 taxonomy evidence

如果 Excel 命中，某些 change 的 evidence 中应出现：

```json
{
  "source": "taxonomy_reference",
  "detail": "matched product/Product taxonomy node ...",
  "weight": 0.26
}
```

这说明该提案受到了 `taxonomy.xlsx` 的支持。

### 10.3 action 类型

在当前默认配置下，正常输出不应包含：

```text
add_concept
```

主要应关注：

```text
add_category_gate
add_module
add_property_type
add_relation_type
```

这符合“冻结顶层 schema，只扩充分类入口、模块、属性槽位和关系槽位”的设计。

## 11. 常见问题

### 11.1 命令进入 `>` 续行状态

通常是上一行的引号、括号或反斜杠写坏了。尤其注意：

```bash
--taxonomy-excel "data/taxonomy.xlsx" \
```

反斜杠后不能有空格。如果已经出现 `>`，按 `Ctrl+C` 回到 shell。

### 11.2 找不到 taxonomy.xlsx

确认路径存在：

```bash
ls -l data/taxonomy.xlsx
```

如果文件不在仓库内，使用绝对路径传给 `--taxonomy-excel`。

### 11.3 Excel 有文件但没有生效

检查：

- 文件后缀必须是 `.xlsx`。
- sheet 名必须包含 `行业分类` 或 `行业+产品`。
- 候选实体的 label/description/alias/statement value 中要能匹配 Excel 的 label 或 code。
- 输出 evidence 中是否出现 `taxonomy_reference`。

### 11.4 没有任何提案

可能原因：

- 候选没有被 `GatePolicy` 或 taxonomy 分到有效 domain。
- `min_review_score` 太高。
- 严格 taxonomy 模式下候选没有命中 taxonomy。
- `prefer_leaf_taxonomy_evidence=true`，但候选命中的是非叶子节点。
- 模型评审拒绝了提案。

## 12. 建议的接入步骤

1. 把真实 Excel 放到 `data/taxonomy.xlsx`。
2. 先用 `examples/offline_wikidata_fixture_taxonomy.json` 跑单轮 `expand-corpus`。
3. 检查 output 中是否出现 `taxonomy_reference` evidence。
4. 用不传 `--taxonomy-excel` 的命令跑一份对照输出。
5. 如果 taxonomy 命中正常，再决定是否开启严格模式。
6. 人工审核 changeset 后，用 `apply-changes` 回写到下一版 schema/config。
7. 用 `iterate-corpus` 验证“生成提案 -> 接受 -> 回写 -> 下一轮”的闭环。

## 13. 总结

`data/taxonomy.xlsx` 的接入点已经在 CLI、taxonomy 解析器和 engine 中打通。正确加入它的方式是：

```text
把 Excel 作为分类参照传入 --taxonomy-excel，
让候选实体在 industry/product 体系中获得额外 evidence 或约束，
但不把 Excel 节点直接当成 schema 概念或实例导入。
```

这样可以在保持 `IncCoreV2.schema` 顶层结构稳定的前提下，继续发现真正值得进入 schema 的分类入口、模块、属性槽位和关系槽位。
