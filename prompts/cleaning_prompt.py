"""数据清洗 Prompt 模板。

3 个 Prompt:
- cleaning_generate_prompt: 生成 YAML 清洗规则
- cleaning_optimize_prompt: 优化失败的 YAML 规则
- cleaning_validate_prompt: 验证清洗结果能否归一化
"""

from __future__ import annotations

# ─────────────────────────── 生成规则 ───────────────────────────

cleaning_generate_prompt = """你是数据清洗专家。根据数据预览和质量问题，生成 YAML 清洗规则。

## 质量问题
{quality_issues}

## 数据预览
{preview}

## 可用算子
{operator_list}

## 算子用法说明

### Dedup - 去重
```yaml
operator: Dedup
by: [id, date]  # 可选，不指定则全行去重
```

### Filter - 条件过滤
```yaml
operator: Filter
condition: "row['amount'] > 0"  # Python 表达式，row 是每行
# 或:
drop_null: true   # 删除含空值的行
drop_empty: true  # 删除全空行
```

### RenameFields - 列名重命名
```yaml
operator: RenameFields
mapping:
  销售额: amount
  日期: date
```

### Map - 类型转换
```yaml
operator: Map
field: amount
func: to_float  # 可选: to_float/to_int/to_str/to_datetime/strip/lower/upper
# 或自定义表达式:
expr: "float(str(row['amount']).replace(',', ''))"
```

### Select - 列选择
```yaml
operator: Select
columns: [date, amount, product]
```

### AddFields - 添加计算列
```yaml
operator: AddFields
fields:
  year: "str(row['date'])[:4]"
  amount_wan: "float(row['amount']) / 10000"
```

### Flat - 展开嵌套
```yaml
operator: Flat
key: tags
target_key: tag  # 可选
```

### Join - 多源关联（仅多数据源时使用）
```yaml
operator: Join
left: main
right: aux
on: product_id
how: left  # left/right/inner/outer
```

## 归一化要求
清洗后数据必须满足以下条件，否则无法归一化：
1. 列名全英文（无中文、空格、特殊字符）
2. 同列类型一致（无 mixed 类型）
3. 有效行数 > 0
4. 可映射到 tabular 形态（有行有列）

## 输出格式
只输出 YAML，不要额外解释。格式如下：

```yaml
nodes:
  step1:
    operator: Dedup
  step2:
    operator: RenameFields
    mapping:
      销售额: amount
  step3:
    operator: Map
    field: amount
    func: to_float
processor:
  chain: [step1, step2, step3]
```
"""

# ─────────────────────────── 优化规则 ───────────────────────────

cleaning_optimize_prompt = """你是数据清洗专家。上一次生成的清洗规则执行失败，需要优化。

## 数据预览
{preview}

## 上一次的 YAML 规则
```yaml
{prev_yaml}
```

## 失败原因
{prev_error}

## 执行日志
{prev_logs}

## 可用算子
{operator_list}

## 归一化要求
1. 列名全英文（无中文、空格、特殊字符）
2. 同列类型一致
3. 有效行数 > 0
4. 可映射到 tabular 形态

## 优化方向
- 检查列名是否拼写正确
- 检查类型转换函数是否合适
- 检查条件表达式语法
- 确保不会产生空 DataFrame
- 简化规则，避免过度清洗

## 输出格式
只输出优化后的 YAML，不要额外解释。格式同上一次。
"""

# ─────────────────────────── 验证结果 ───────────────────────────

cleaning_validate_prompt = """判断以下清洗后的数据能否归一化为标准数据结构（VizDataset）。

## 清洗后数据预览
{preview}

## 归一化要求
1. 列名全英文（无中文、空格、特殊字符）
2. 同列类型一致（无 mixed 类型）
3. 有效行数 > 0
4. 可映射到 tabular 形态（有行有列）

## 判断标准
- pass=true: 所有要求都满足，可以归一化
- pass=false: 有要求不满足，需要继续清洗

## 输出 JSON
只输出 JSON，不要额外解释。格式如下：

```json
{{
  "pass": true,
  "reason": "列名全英文，类型一致，行数充足",
  "suggestions": []
}}
```

或：

```json
{{
  "pass": false,
  "reason": "存在中文列名: 金额, 日期",
  "suggestions": ["使用 RenameFields 将中文列名转为英文"]
}}
```
"""

# ─────────────────────────── 多源 Join 检测 ───────────────────────────

join_detection_prompt = """你是数据分析专家。判断以下多个数据源是否需要关联（Join）。

## 数据源列表
{sources}

## 判断标准
- 如果两个数据源有共同的列（如 product_id, user_id），且关联后能提供更丰富的信息，则建议 Join
- 如果数据源之间没有明显关联，则不需要 Join
- 优先选择信息更丰富的一方作为主表（left）

## 输出 JSON
只输出 JSON，不要额外解释。格式如下：

```json
{{
  "need_join": false,
  "reason": "两个数据源没有共同的关联列"
}}
```

或：

```json
{{
  "need_join": true,
  "left": "orders",
  "right": "products",
  "on": "product_id",
  "how": "left",
  "reason": "orders 和 products 通过 product_id 关联，可获得产品名称等补充信息"
}}
```
"""

# ─────────────────────────── 多源清洗规则生成 ───────────────────────────

cleaning_multi_source_prompt = """你是数据清洗专家。多个数据源需要关联（Join）后清洗。

## 数据源预览
{sources_preview}

## Join 配置
{join_config}

## 质量问题
{quality_issues}

## 可用算子
{operator_list}

## 算子用法说明

### Join - 多源关联
```yaml
operator: Join
left: main      # 主数据源名称
right: aux      # 辅助数据源名称
on: product_id  # 关联列
how: left       # left/right/inner/outer
```

### 其他算子（同单源清洗）
Dedup, Filter, RenameFields, Map, Select, AddFields, Flat

## 归一化要求
1. 列名全英文
2. 同列类型一致
3. 有效行数 > 0
4. 可映射到 tabular 形态

## 输出格式
只输出 YAML，不要额外解释。格式如下：

```yaml
inputs:
  main: {first_source}
  aux: {second_source}
nodes:
  join1:
    operator: Join
    left: main
    right: aux
    on: product_id
    how: left
  step1:
    operator: Dedup
  step2:
    operator: RenameFields
    mapping:
      销售额: amount
processor:
  chain: [join1, step1, step2]
```
"""
