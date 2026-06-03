# Agent Tool优化

## 添加Tool工具
主要添加一些查询数据库的tool工具。
（1）查询有哪些数据表，连接的postgresql中的ecommerce数据库下有哪些表，返回有哪些表信息，然后给出每个表存储了哪些数据的描述信息；
（2）查询某个数据表有哪些字段，并给出每个字段的含义；
（3）查询某个数据表的某个字段有哪些取值，允许多字段联合查询；
注意每个tool的输出格式你需要预先生成一个版本，然后需要向我核对一下。

## 优化目录结构
将rag/prompt.py也放到/agent/prompt下，便于提示词统一管理。

## 优化Agent
为以下几个Agent添加tool调用。

### 优化extraction节点
该节点负责电商查询意图拆解。
第一步，首先应该生成category和sub_category，这两个字段取值参考category_lookup中有哪些(category,sub_category)对，进一步地，生成field字段，其取值参考category_lookup

其输出中的field、和需要参考，value、expanded_values


考虑加一下tool，让模型去查询有哪些数据表（带数据表作用的介绍），每个数据表有哪些字段，数据表中字段的取值有哪些？进一步通过这些tool优化一下prompt中注入的某些属性的取值范围。进一步优化一下意图提取（如果某些属性属于数据库的专业字段，那么就用SQL的方式提取，否则使用RAG）这方面；