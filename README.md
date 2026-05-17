# Wikidata Ontology Expander

这个项目参考 `ontokg-wikidata.pdf` 中 OntoKG 自动扩充思想，实现一条可运行的 Wikidata 本体扩充管线：

1. 读取种子本体 schema，识别实体类型、属性、关系和模块。
2. 根据种子术语从 Wikidata 召回候选实体。
3. 用类型、描述、属性、关系和模块线索进行证据评分。
4. 生成待审核的本体扩充 ChangeSet，而不是直接污染原始 schema。
5. 保留 Wikidata QID、属性 PID、证据文本、置信度和人工复核标记。

## 项目结构

```text
src/wikidata_ontology_expander/
  cli.py              # 命令行入口
  engine.py           # 扩充编排流程
  models.py           # 数据模型
  schema_parser.py    # IncCore/类 schema 解析器
  scoring.py          # 候选评分和 gate 策略
  wikidata.py         # Wikidata API/SPARQL 客户端
examples/
  config.json         # 扩充参数示例
  seed_schema.json    # 种子实体示例
tests/
  test_*.py           # 离线单元测试
```

## 安装

```powershell
cd E:\vs_projects\Ontology\wikidata_ontology_expander
python -m pip install -e .
```

如果暂时不安装，也可以直接使用：

```powershell
$env:PYTHONPATH="E:\vs_projects\Ontology\wikidata_ontology_expander\src"
python -m wikidata_ontology_expander.cli --help
```

## 运行示例

下面命令会读取 `IncCoreV2.schema` 和示例种子，联网访问 Wikidata，并输出变更集：

```powershell
python -m wikidata_ontology_expander.cli expand `
  --schema E:\vs_projects\Ontology\IncCoreV2.schema `
  --seeds E:\vs_projects\Ontology\wikidata_ontology_expander\examples\seed_schema.json `
  --config E:\vs_projects\Ontology\wikidata_ontology_expander\examples\config.json `
  --output E:\vs_projects\Ontology\wikidata_ontology_expander\out\changeset.json `
  --timeout 60 `
  --continue-on-error
```

默认示例是小规模试跑：`examples/seed_schema.json` 中有 4 个种子实体，`examples/config.json` 中
`max_candidates_per_seed` 为 2，因此最多深入拉取 8 个 Wikidata 候选实体。

输出的 `changeset.json` 包含：

- `add_entity`: 建议新增的本体实体或分类节点。
- `add_relation`: 建议新增的层级、产业、材料、制造商等关系。
- `enrich_property`: 建议补全的别名、描述、官网、时间等属性。
- `review_required`: 低于自动接受阈值但有证据的候选。

## 方法对应关系

论文中的关键机制在项目中的落点如下：

- category + module 种子 schema：`schema_parser.py` 和 `seed_schema.json`
- 分类与未分类实体识别：`ExpansionEngine._classify_candidate`
- gate values / module indicators：`GatePolicy` 和 `ModuleProfile`
- value properties 扩充：`PropertyMapper`
- 迭代 refinement 与人工审核：`ChangeSet`、`review_required`、`confidence`

## 离线测试

测试不访问 Wikidata，使用 fake client：

```powershell
cd E:\vs_projects\Ontology\wikidata_ontology_expander
$env:PYTHONPATH="E:\vs_projects\Ontology\wikidata_ontology_expander\src"
python -m unittest discover -s tests
```

## 人工审查页面

项目内置了一个零依赖的静态审查工作台：

```text
E:\vs_projects\Ontology\wikidata_ontology_expander\review_ui\index.html
```

直接用浏览器打开即可。页面支持：

- 导入 `changeset.json`
- 按动作、状态、置信度和关键词筛选
- 查看 Wikidata QID、模块、字段、建议值和证据
- 编辑实体类型、模块、字段、父节点、建议值和审查意见
- 将每条变更标记为接受、拒绝或需复核
- 导出 `reviewed_changeset.json`

## 离线小样本运行

如果服务器无法访问 `www.wikidata.org`，可以先用离线 fixture 验证全流程：

```bash
python -m wikidata_ontology_expander.cli expand \
  --schema data/IncCoreV2.schema \
  --seeds examples/seed_schema.json \
  --config examples/config.json \
  --output out/changeset.json \
  --offline-fixture examples/offline_wikidata_fixture.json
```

这个模式只使用 `examples/offline_wikidata_fixture.json` 中的 4 个 Wikidata-like 实体，不访问网络。

如果想用稍大的离线样本测试，可以运行：

```bash
python -m wikidata_ontology_expander.cli expand \
  --schema data/IncCoreV2.schema \
  --seeds examples/seed_schema_extended.json \
  --config examples/config.json \
  --output out/changeset_extended.json \
  --offline-fixture examples/offline_wikidata_fixture_extended.json
```

扩展样本包含 10 个种子实体和 10 个 Wikidata-like 实体，覆盖产业、产品、企业、技术、专利和区域。
