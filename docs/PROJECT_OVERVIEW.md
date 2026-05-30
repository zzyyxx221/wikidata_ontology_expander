# 项目说明文档

## 1. 项目是什么

`wikidata_ontology_expander` 是一个面向 **ontology/schema 扩充** 的项目。

它的目标不是构建完整的实例知识图谱，也不是给单个实体补齐属性值，而是：

- 从外部知识源实例中提炼 schema 层信号
- 生成适合人工审核的本体扩充提案
- 支持把接受后的提案回写到 `schema` 和 `config`
- 支持基于回写结果继续自动跑下一轮 refinement

当前默认数据源是 Wikidata，但项目内部已经尽量把“外部编号”从核心逻辑中剥离掉了。外部 `QID` 现在主要作为证据来源保留，不再作为 schema 提案的身份主键。

## 2. 项目解决什么问题

很多知识图谱项目一开始只有一个较小的种子 schema。问题通常不是“没有实例”，而是：

- 现有领域划分不够覆盖真实语料
- 已有实体类型缺少必要属性槽位
- 已有关系模块不够用
- 某些候选实体可以看出属于某个领域，但挂不到任何现有模块上
- 某些候选实体甚至连领域都分不进去

这个项目就是用外部实例作为观测信号，反过来帮助扩充 schema。

一句话概括：

**用实例信号做 schema refinement，而不是做 instance enrichment。**

## 3. 项目边界

### 项目要做的事

- 读取种子 schema
- 召回外部候选实体
- 对候选进行领域和模块分类
- 从候选 statement 中归纳 schema 级提案
- 输出 changeset 供人工审核
- 回写接受后的提案
- 基于更新后的 schema/config 继续迭代

### 项目不做的事

- 不追求完整实例图谱构建
- 不默认输出实例级 description、alias、URL、日期等补全结果
- 不把每个 Wikidata statement 原样映射进 schema
- 不把外部编号当作内部稳定主键

## 4. 核心思想

这个项目参考了 OntoKG 的基本思路，但做了更工程化的落地：

1. 用种子 schema 建立初始分类面
2. 用外部实体作为观察样本
3. 找出 schema 的覆盖缺口
4. 产出 schema 层提案
5. 接受部分提案后回写
6. 再用更新后的 schema 继续下一轮

所以项目不是一次性抽取器，而是一个 **面向迭代 refinement 的 schema proposal engine**。

## 5. 当前架构

项目主要由下面几个模块组成：

```text
src/wikidata_ontology_expander/
  cli.py              # 命令行入口
  engine.py           # 核心扩充编排逻辑
  refinement.py       # 提案回写与多轮迭代
  models.py           # 数据模型
  schema_parser.py    # schema 解析器
  scoring.py          # 分类与打分
  wikidata.py         # 在线 Wikidata 客户端
  fixture_client.py   # 离线 fixture 客户端
  model_review.py     # 可选模型评审层
```

### 5.1 `schema_parser.py`

负责把 `.schema` 文本解析成内部结构 `SchemaDocument`：

- `domains`
- `entities`
- `modules`
- `fields`

它会识别：

- 领域段落，例如 `# 产品域`
- 实体定义，例如 `Product(Product): EntityType`
- 属性段和关系段
- `#modules:` 标记

### 5.2 `models.py`

定义项目里的核心对象，例如：

- `SeedEntity`
- `WikidataEntity`
- `WikidataStatement`
- `ModuleProfile`
- `Change`
- `ChangeSet`
- `RefinementReport`

这里有两个很重要的设计点：

1. `WikidataEntity.source_id` 是可选来源标识，不再承担 schema 主键角色
2. `Change` 的去重现在由提案语义决定，而不是由单个 Wikidata 编号决定

### 5.3 `scoring.py`

负责把候选实体分配到某个 category/domain 和 module。

分类信号主要来自：

- 种子词与候选 label/alias/description 的匹配
- statement 的 property 命中
- module 的 indicator terms
- `category_gate_labels`

输出包括：

- `category`
- `module`
- `score`
- `evidence`

### 5.4 `engine.py`

这是项目的主引擎，负责：

- 收集候选实体
- 调用分类器
- 识别 schema 缺口
- 聚合候选证据
- 生成 schema 提案

目前支持的提案类型包括：

- `add_category_gate`
- `add_module`
- `add_concept`
- `add_property_type`
- `add_relation_type`

### 5.5 `refinement.py`

负责把“提案”变成“下一轮输入”。

它做两件事：

1. 把 accepted changeset 回写到 `schema` 和 `config`
2. 自动按多轮执行：
   - 生成提案
   - 自动接受高置信提案
   - 回写
   - 继续下一轮

## 6. 数据流

项目当前的主数据流如下：

```text
seed schema + config + seeds/corpus
  -> parse schema
  -> fetch or load candidate entities
  -> classify candidates into category/module
  -> detect schema gaps
  -> aggregate evidence
  -> generate changeset
  -> human review or auto-accept
  -> write back schema/config
  -> next refinement round
```

## 7. 提案类型说明

### 7.1 `add_category_gate`

含义：

- 某个候选当前无法进入任何已有 category
- 但它的 `P31/P279` 类型强烈暗示它应该属于某个 domain
- 因此建议把该类型标签加入对应 category 的 gate

回写位置：

- 写入 `config` 中对应 profile 的 `category_gate_labels`

### 7.2 `add_module`

含义：

- 某个候选已经能进入某个 category
- 但没有任何现有 module 适合承载它暴露出的 schema 信号
- 因此建议新增一个模块容器

回写位置：

- 作为人工审核信号保留
- 当前 `.schema` 文本格式没有空模块的独立语法，因此自动回写不会把 `add_module` 当作字段写入
- 真正新增属性或关系槽位时，使用 `add_property_type` / `add_relation_type`

### 7.3 `add_concept`

含义：

- 某个候选不是现有 schema 中已知概念
- 并且看起来是 schema 层值得建模的概念

回写位置：

- 在 `schema` 中新增 `ConceptType`

### 7.4 `add_property_type`

含义：

- 某个领域下缺少新的属性槽位
- 该槽位值是文本、日期、URL 等非实体型值

回写位置：

- 在 `schema` 的 `properties:` 段新增字段
- 在 `config.property_map` 中补充 property 与 PID 的映射

### 7.5 `add_relation_type`

含义：

- 某个领域下缺少新的关系类型
- 该槽位指向另一个实体类型

回写位置：

- 在 `schema` 的 `relations:` 段新增字段
- 在 `config.modules[*].relation_properties` 中补充 relation 到 PID 的映射

## 8. 运行模式

### 8.1 `expand`

使用 seed terms 从 Wikidata 或离线 fixture 召回候选，再做 schema 扩充。

适合：

- 从种子实体出发做定向扩充

### 8.2 `expand-corpus`

直接使用本地 corpus 里的候选实体集合，不经过检索。

适合：

- 已经有一批待分析实体
- 想稳定复现实验
- 网络受限环境

### 8.3 `apply-changes`

把已经接受的 changeset 回写到：

- 新 schema 文件
- 新 config 文件

### 8.4 `iterate`

基于 seeds 做多轮自动 refinement。

### 8.5 `iterate-corpus`

基于本地 corpus 做多轮自动 refinement。

## 9. 为什么 schema 和 config 要分开回写

这是当前实现里很重要的一个设计：

- `schema` 负责定义“图谱结构长什么样”
- `config` 负责定义“如何把候选路由到这些结构里”

例如：

- 新增 `manufacturer` 关系字段，属于 schema 结构
- `manufacturer -> P176` 这种映射，属于 config 路由规则
- `battery` 可以作为产品域 gate label，这也是 config 规则

这样拆分有两个好处：

1. schema 可读性更强
2. 路由策略可以独立演化

## 10. 当前项目与论文思路的关系

这个项目已经实现了论文思路中的一部分关键闭环：

- 初始分类
- 缺口识别
- schema 提案生成
- 提案回写
- 多轮迭代

但仍然是一个“保守版工程实现”，还没有完全覆盖论文里更复杂的部分，例如：

- 更强的 gate expansion 统计逻辑
- module merge / split
- 更完整的人工审核工作流
- 更细的 category oracle / module oracle

当前策略是先把最有工程价值的能力做稳：

- 领域补洞
- 模块补洞
- 槽位补洞
- 迭代闭环

## 11. 一个典型工作流

### 11.1 单轮提案生成

```bash
python -m wikidata_ontology_expander.cli expand-corpus \
  --schema examples/seed_schema.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture.json \
  --output out/schema_changeset.json
```

### 11.2 人工审核后回写

```bash
python -m wikidata_ontology_expander.cli apply-changes \
  --schema examples/seed_schema.schema \
  --config examples/config.json \
  --changes out/accepted_changeset.json \
  --schema-output out/seed_schema.next.schema \
  --config-output out/config.next.json
```

### 11.3 自动多轮迭代

```bash
python -m wikidata_ontology_expander.cli iterate-corpus \
  --schema examples/seed_schema.schema \
  --config examples/config.json \
  --offline-fixture examples/offline_wikidata_fixture.json \
  --output-dir out/refinement_rounds \
  --rounds 3 \
  --accept-threshold 0.72
```

## 12. 输出产物说明

单轮输出通常包括：

- `changeset.json`
- `accepted_changeset.json`
- `schema.next.schema`
- `config.next.json`

多轮输出通常按轮次分目录，例如：

```text
out/refinement_rounds/
  round_1/
    changeset.json
    accepted_changeset.json
    schema.next.schema
    config.next.json
  round_2/
    ...
```

## 13. 测试与验证

运行测试：

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

当前测试重点覆盖：

- schema 解析
- 分类打分
- 提案生成
- 编号无关的去重逻辑
- 提案回写
- 多轮 refinement 闭环

## 14. 适合下一步继续做的方向

- 增加更强的 gate expansion 排序策略
- 增加 module merge / split 提案
- 给 `review_ui` 接入 accepted/rejected 工作流
- 支持更通用的外部知识源，而不只是假定 Wikidata 结构
- 增加 schema diff 和回写审计日志

## 15. 总结

这个项目现在最准确的定位是：

**一个基于外部实体信号、面向 ontology/schema 扩充的迭代式提案引擎。**

它的核心价值不在于“抽到了多少实例属性”，而在于：

- 是否能发现 schema 缺口
- 是否能把缺口表达成可审核的结构化提案
- 是否能在接受提案后推动下一轮 schema 演化
