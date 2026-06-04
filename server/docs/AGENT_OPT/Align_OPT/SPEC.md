# 问题
我发现当前项目存在一些对齐问题。

## 重构retrive相关实现
去除掉search.py中当前的非流式模式，现在/api/search接口功能完全采用agent工作流进行实现。

在server\log\app_20260604_170431.log运行日志中，只显示进行了semantic_search，我查看了一下当前代码，发现很可能是_category_task中试图将意图转换为 SubQuery 列表，以兼容现有 Retriever 接口 subs = _intent_to_sub_queries(intent)导致出现的问题，解析不出来keyword检索。

重构server\app\services\retriever_service.py中的实现，使其完全服务于当前agent工作流进行实现。

重构rag目录下的几个python文件，原来这些代码也服务于search.py中当前的非流式模式，现在也对这些代码进行重构，使其完全服务于当前agent工作流进行实现，并添加到/service中。

注意：重构的代码不一定还要放在一个新文件中，可以根据其功能融合进services目录下已有的几个服务提供代码文件中。
