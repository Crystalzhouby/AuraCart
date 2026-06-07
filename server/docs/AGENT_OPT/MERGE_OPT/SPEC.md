# 合并一些LLM调用

## 合并"查询重写+场景提取"
去除router节点中的查询重写LLM调用，欢迎语生成直接基于历史对话和用户原查询，不在基于重写的查询。
对于当前接收重写后查询的extraction和scenario_gen节点，同样使用原查询。将近几轮历史用户查询和当前用户查询输入给LLM，让LLM推断当前用户查询所需要category和sub_category。


## 合并"结束语生成+选项生成"
将OPTION_GEN_SYSTEM和ENDING_SYSTEM进行合并，商品推荐结束语和选项生成一次LLM完成。调整其输出格式为：
```
{
    "ending": "<value>"
    "next_options":
    [
        "<value>",
        "<value>"
    ]
}
```