属性和底层数据
DataFrame.index：DataFrame 的索引（行标签）。

DataFrame.columns：DataFrame 的列标签。

DataFrame.dtypes：返回 DataFrame 中的数据类型。

DataFrame.info([verbose, buf, max_cols, ...])：打印 DataFrame 的简洁摘要。

DataFrame.select_dtypes([include, exclude])：根据列的数据类型返回 DataFrame 列的子集。

DataFrame.values：返回 DataFrame 的 Numpy 表示。

DataFrame.axes：返回一个表示 DataFrame 轴的列表。

DataFrame.ndim：返回一个表示轴/数组维数的整数。

DataFrame.size：返回一个表示此对象中元素数量的整数。

DataFrame.shape：返回一个表示 DataFrame 维度的元组。

DataFrame.memory_usage([index, deep])：返回每列的内存使用量（以字节为单位）。

DataFrame.empty：指示 Series/DataFrame 是否为空。

DataFrame.set_flags(*[, copy, ...])：返回一个带有更新标志的新对象。

转换
DataFrame.astype(dtype[, copy, errors])：将 pandas 对象强制转换为指定的数据类型 dtype。

DataFrame.convert_dtypes([infer_objects, ...])：将列从 numpy 数据类型转换为支持 pd.NA 的最佳数据类型。

DataFrame.infer_objects([copy])：尝试为 object 列推断更合适的数据类型。

DataFrame.copy([deep])：复制此对象的索引和数据。

DataFrame.to_numpy([dtype, copy, na_value])：将 DataFrame 转换为 NumPy 数组。

索引、迭代
DataFrame.head([n])：返回前 n 行。

DataFrame.at：通过行/列标签对访问单个值。

DataFrame.iat：通过整数位置通过行/列对访问单个值。

DataFrame.loc：通过标签或布尔数组访问一组行和列。

DataFrame.iloc：纯粹基于整数位置的索引，用于按位置选择。

DataFrame.insert(loc, column, value[, ...])：在指定位置将列插入 DataFrame。

DataFrame.iter()：迭代信息轴。

DataFrame.items()：迭代（列名，Series）对。

DataFrame.keys()：获取“信息轴”（更多信息请参阅索引）。

DataFrame.iterrows()：将 DataFrame 行迭代为（索引，Series）对。

DataFrame.itertuples([index, name])：将 DataFrame 行迭代为命名元组。

DataFrame.pop(item)：返回项并将其从 DataFrame 中删除。

DataFrame.tail([n])：返回最后 n 行。

DataFrame.xs(key[, axis, level, drop_level])：从 Series/DataFrame 返回横截面。

DataFrame.get(key[, default])：获取对象中给定键（例如 DataFrame 列）的项。

DataFrame.isin(values)：DataFrame 中的每个元素是否包含在 values 中。

DataFrame.where(cond[, other, inplace, ...])：替换条件为 False 的值。

DataFrame.mask(cond[, other, inplace, axis, ...])：替换条件为 True 的值。

DataFrame.query(expr, *[, parser, engine, ...])：使用布尔表达式查询 DataFrame 的列。

DataFrame.isetitem(loc, value)：在位置 loc 的列中设置给定值。