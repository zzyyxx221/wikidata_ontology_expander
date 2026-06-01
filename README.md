# Wikidata Ontology Expander

这个项目现在面向的是 **schema / 本体模式层扩充**，而不是实例属性补全。

完整中文项目文档见 [docs/PROJECT_OVERVIEW.md](/Users/zyx/projects/wikidata_ontology_expander/docs/PROJECT_OVERVIEW.md)。

技术架构与 `data/taxonomy.xlsx` 接入说明见 [docs/TECHNICAL_ARCHITECTURE_AND_TAXONOMY.md](/Users/zyx/projects/wikidata_ontology_expander/docs/TECHNICAL_ARCHITECTURE_AND_TAXONOMY.md)。

项目目的可以明确为：

- 从外部知识源实例中归纳 **值得进入 ontology/schema 的结构化提案**
- 帮助人工扩充领域、本体类型、模块、属性槽位和关系类型
- 不以构建完整实例知识图谱为目标，也不直接做实例级 enrichment

它参考 OntoKG 的核心思路：从种子 schema 和外部知识库实例中，发现值得进入本体的新概念、新属性槽位和新关系类型，并把结果输出为待审核提案。

## 当前实现目标

1. 读取种子本体 schema，识别领域、实体类型、属性模块和关系模块。
2. 根据种子术语从 Wikidata 召回候选实例。
3. 使用 gate 属性、提示词和 schema 模块信息对候选进行领域分类。
4. 从候选实例的 statement 中归纳 schema 级增量：
   - `add_category_gate`
   - `add_module`
   - `add_concept`
   - `add_property_type`
   - `add_relation_type`
5. 可选地调用模型 API，对提案做“是否值得进入本体模式层”的二次评审和规范化。
6. 输出 ChangeSet 供人工审核，而不是直接修改 schema。
7. 对已接受提案，可以回写到 schema/config，并继续自动触发下一轮 refinement。

## 不再默认输出的内容

为了避免把 ontology expansion 退化成 instance enrichment，以下内容默认不再作为扩充结果：

- description / alias 这类实例属性值
- `subclassOf` 这类实例现成关系值
- URL、日期等单个实例字段补全

这些值仍然可以作为证据参与判断，但不再直接出现在最终提案中。

## 项目结构

```text
src/wikidata_ontology_expander/
  cli.py              # 命令行入口
  engine.py           # schema-level 扩充编排流程
  models.py           # 数据模型
  model_review.py     # 可选模型评审层
  schema_parser.py    # schema 解析器
  scoring.py          # 候选分类和打分
  wikidata.py         # Wikidata 客户端
```

## 运行示例

```bash
python -m wikidata_ontology_expander.cli expand \
  --schema data/IncCoreV2.schema \
  --seeds examples/seed_schema.json \
  --config examples/config.json \
  --output out/schema_changeset.json
```

离线模式：

```bash
python -m wikidata_ontology_expander.cli expand \
  --schema data/IncCoreV2.schema \
  --seeds examples/seed_schema.json \
  --config examples/config.json \
  --output out/schema_changeset.json \
  --offline-fixture examples/offline_wikidata_fixture.json
```

## 输出说明

输出的 `changeset.json` 现在以 schema 提案为主：

- `add_category_gate`: 建议把新的 gate type 纳入某个 category/domain
- `add_module`: 建议在某个 domain 下增加新的模块容器；不直接回写字段
- `add_concept`: 建议新增概念或类型节点
- `add_property_type`: 建议新增属性槽位
- `add_relation_type`: 建议新增关系类型

每条提案会保留：

- `domain`
- `entity_type`
- `module`
- `field`
- `target_type`
- `support`
- `source_entity_ids`
- `examples`
- `evidence`
- `confidence`
- `rationale`

## 接受提案并回写

如果已经有一份人工筛选后的 accepted changeset，可以直接回写：

```bash
python -m wikidata_ontology_expander.cli apply-changes \
  --schema examples/seed_schema.schema \
  --config examples/config.json \
  --changes out/accepted_changeset.json \
  --schema-output out/seed_schema.next.schema \
  --config-output out/config.next.json
```

说明：

- `schema` 负责承载实体类型、模块、属性槽位和关系槽位
- `config` 负责承载分类和路由规则，例如 `relation_properties`、`property_map`、`category_gate_labels`

## 自动多轮迭代

如果想自动完成“生成提案 -> 自动接受高置信提案 -> 回写 -> 继续下一轮”，可以运行：

```bash
python -m wikidata_ontology_expander.cli iterate-corpus \
  --schema examples/seed_schema.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture.json \
  --output-dir out/refinement_rounds \
  --rounds 3 \
  --accept-threshold 0.72
```

每一轮会输出：

- `changeset.json`
- `accepted_changeset.json`
- `schema.next.schema`
- `config.next.json`

## 模型 API 评审

可以在配置里开启可选的模型评审：

```json
{
  "model_review": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-5-mini",
    "api_base": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
    "temperature": 0.0,
    "max_output_tokens": 600
  }
}
```

模型评审的职责是：

- 拒绝实例级补全提案
- 判断提案是否真的属于 schema 层
- 规范化概念名、关系名和目标类型

## 设计取向

相较于之前的实现，现在的设计更接近你要的目标：

- 从“给实体补字段”转为“给 schema 提建议”
- 从“直接搬运 Wikidata statement”转为“聚合多实例信号后归纳模式”
- 从“单次提案输出”扩展到“面向迭代 refinement 的 gap 分析”
- 允许引入模型做模式层判断，而不只是规则打分

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
