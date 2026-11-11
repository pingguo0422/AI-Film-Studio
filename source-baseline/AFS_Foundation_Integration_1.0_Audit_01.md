# AFS Foundation Integration 1.0 — Audit 01

- 日期：2026-11-09
- 审查范围：资料库中的 Footage-Mode 2.2-B 包及其恢复清单、README、测试报告；隔离副本的实际复测；AFS DB-01—DB-05 资料可用性盘点。
- 原始包：`Footage-Mode-2.2-B.zip`
- 原始包大小：176,476 bytes
- 工作方式：复制到独立审查目录并解压；没有修改资料库原始 ZIP，也没有覆盖 Footage-Mode 原工作区。

## 1. 实际复测结果

| 检查 | 结果 |
|---|---|
| ZIP 完整性 | PASS |
| 包内文件数 | 81 |
| `python -m unittest discover -s tests -v` | 51 passed, 0 failed |
| `python -m compileall -q scripts tests` | PASS |
| `python scripts/footage_mode.py selftest` | PASS，4-shot fixture |
| `python scripts/adapt_acting.py selftest` | PASS，4 ACTING TASK blocks / 4 shots |
| 8.1 coverage optimizer，`--max-shots 18` | PASS，18 selected / 80 candidates |

8.1 输出事件状态：
- covered：5
- partially_covered：16
- not_selected：31
- 总事件：52

优化器报告的 `coverage_ratio=0.615565` 是按事件权重和 required dimensions 加权的维度覆盖率，不是“完整覆盖事件比例”。同一结果中：
- 完整覆盖事件比例：5 / 52 = 9.62%
- 至少有一个维度被覆盖的事件比例：(5 + 16) / 52 = 40.38%
- 未加权维度覆盖比例：81 / 157 = 51.59%
- 加权维度覆盖比例：61.56%

因此建议后续输出显式拆分字段：`weighted_dimension_coverage_ratio`、`dimension_coverage_ratio`、`fully_covered_event_ratio`、`any_coverage_event_ratio`，避免把单一 `coverage_ratio` 误读为事件覆盖率。

## 2. 静态代码审查发现

### FMD-VAL-001 — 输入结构验证不够健壮（建议修复）

文件：`scripts/director_decision_engine.py`，`validate_events()`。

隔离副本中的额外边界探测：
- `source` 被错误传成字符串时，抛出 `AttributeError`（不是可识别的输入校验错误）。
- `event_types` 被错误传成字符串时，未拒绝；字符串被逐字符迭代，事件会被错误归类为没有 required dimensions，可能输出 `not_selected`。
- `coverage_priority` 被错误传成列表时，抛出 `TypeError: unhashable type: 'list'`，而不是结构化校验错误。
- `source.line_start` / `line_end` 使用布尔值 `True` 时被当作整数接受，因为 Python 中 `bool` 是 `int` 的子类。

建议：
1. 对 `source`、`scene`、`event_types`、`participants`、`linked_event_ids`、`coverage_priority` 做显式类型检查。
2. 对行号使用 `type(value) is int`，拒绝 bool。
3. 统一抛出包含 event_id、field path 和错误原因的 `ValueError` 或项目级 validation exception。
4. 将 JSON Schema 验证纳入入口流程，但仍保留业务语义校验。
5. 新增上述四类负向测试，并加入空列表、未知事件类型和非法嵌套对象用例。

### FMD-METRIC-001 — 覆盖率字段名称容易引起误解（建议修复）

当前 `optimization.coverage_ratio` 为加权 required-dimension 覆盖率。它不等于完全覆盖事件数 / 总事件数，也不等于至少被部分覆盖的事件比例。

建议保留向后兼容字段一段过渡期，同时增加语义明确的新字段，并在 schema / README / report 中解释计算公式。

### FMD-COV-001 — 18 镜头预算是压力测试参数，不是生产建议

当前 18 镜头预算下 31 个事件没有被选中，16 个事件只有部分维度覆盖。测试报告的预算敏感性显示，预算变化会显著改变完整覆盖数量。必须把预算设定、覆盖目标和人工取舍作为导演审批决策，不能将算法结果自动视为拍摄计划。

## 3. Footage-Mode → AFS 适配时必须保留的契约

1. 来源类型：当前 8.1 事件样本来自 ACTING TASK，应映射为 `SOURCE_ACTING_TASK`；只有真正从原始剧本解析的输入才可标记 `SOURCE_SCREENPLAY`。
2. 源文本追溯：事件 `source.line_start`、`source.line_end`、`source.exact_text` 必须保留；不得将其压缩成不可追溯的摘要。
3. 事件语义：保留 `event_types`、`event_cluster_id`、`linked_event_ids`、`observable_action`、`dramatic_state`、`information_delta`、`power_relation`、`visual_evidence`、`coverage_priority`、`confidence`、`human_review_required` 和 `inference_policy`。
4. 覆盖语义：`covered`、`partially_covered`、`not_selected` 必须按显式 required dimensions 计算；未选候选不能计入覆盖；master/context shot 未显式映射维度不得计入覆盖。
5. 并行轨道：保留稳定 `character_id`、character tracks、同场并发和跨场 `parallel_with` 关系；不能将并行轨道串行化。
6. 时间来源：`authored` 与 `estimated` 必须分开存储；source time 与 clip-local render time 必须分开；适配器不得把估算时间伪装成实测时间。
7. 镜头和摄像机：保留 `shot_id`、`camera` / `camera_id`、source range 和各镜头独立本地 render range。
8. QC：错误、警告、原因、原始输出和工具版本必须可追溯。
9. Visual Bible：工具产生的 draft 不得映射为 AFS approved；任何 `director_approved` / `production_locked` 都必须有可验证的人类审批记录和权限依据。
10. 执行隔离：Adapter 在独立工作目录运行原生工具，保留原始输入快照、包版本、命令、退出码、输出摘要和校验结果。

## 4. AFS 数据基础设施资料盘点结果

本次资料库检索与文件列表中，确认存在 Footage-Mode 2.2-A / 2.2-B ZIP、README、恢复清单、测试报告、事件 JSON 和覆盖决策输出。

本次没有找到可供真实代码审查的 AFS DB-01—DB-05 SQL migration 文件、Alembic migration tree、PostgreSQL schema dump、AFS backend repository 或统一 ERD 文件。因此：
- DB-01—DB-05 当前仍只能依据对话中已确认的设计基线做静态整合。
- 不能声称已完成 AFS 数据库代码审查、迁移执行或 PostgreSQL 测试。
- 要完成真实数据库审查，需要取得 AFS 当前开发包（至少包含 migrations / SQL、backend models、database config、tests；敏感凭据请移除）。

## 5. 初步整合建议（尚非最终迁移计划）

在看到真实 SQL 之前，建议迁移分层顺序如下，最终顺序需根据实际外键依赖图调整：

1. `000_core_extensions_roles`：扩展、schema、角色和基础权限约定。
2. `010_projects_members`：项目与成员。
3. `020_entities_versions_relations_audit`：统一实体、实体版本、关系、审计；实体工作版本/批准版本指针须处理循环 FK（可先建表后补约束）。
4. `030_approval_dependencies_impact`：审批工作流、步骤、记录、依赖、变更事件和影响报告。
5. `040_dam_assets_provenance_qc`：媒体资产、资产版本、对象关联、溯源、处理任务、QC。
6. `050_agent_skill_model_registry`：Agent、Skill、Model、Provider 及版本注册。
7. `060_tasks_runs_orchestration_events`：Task DAG、各类 Run、编排计划、消息、Outbox / Inbox。
8. `070_footage_mode_integration`：Integration Source / Run / Mapping / Snapshot、源范围、并行轨道、覆盖决策。
9. `080_constraints_indexes_triggers_policies`：跨表约束、不可变触发器、索引、RLS / 授权策略及验证。

注意：此列表是审查用候选顺序，不可直接当作已经验证的 migration plan。尤其 projects/entities/approvals/DAM/agent runs 之间的 FK 与项目归属约束，必须根据真实 DDL 建图后定稿。

## 6. 当前阶段状态

- Footage-Mode 2.2-B 隔离副本复测：`TESTED`（本次复测范围内）。
- Footage-Mode 输入校验边界：发现待修复问题，`REVIEW_REQUIRED`。
- 覆盖率指标命名：发现待改进项，`REVIEW_REQUIRED`。
- DB-01—DB-05 统一迁移审查：`BLOCKED_ON_SOURCE_PACKAGE`（缺少真实 AFS SQL / migrations / backend 项目文件）。
- PostgreSQL 迁移执行：`NOT_EXECUTED`。
- AFS Adapter 真实集成：`NOT_IMPLEMENTED / NOT_TESTED`。

## 7. 下一步

请提供 AFS 当前开发工作区压缩包，或至少提供 DB-01 至 DB-05 的 SQL / migration 文件及 backend models。收到后先做只读盘点、迁移依赖图和跨表约束审查；未经备份和确认，不覆盖任何现有文件。
