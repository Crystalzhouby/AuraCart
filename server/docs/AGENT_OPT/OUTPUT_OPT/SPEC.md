## 添加流式/非流式输出开关
每个agent可流式/非流式输出，调用/api/search时，通过参数stream设置是否可以流式输出，stream=false表示非流式输出，stream=true表示流式输出，默认为流式输出。

## 流式输出细化方案
将welcome、category_intro和ending按照token为单位进行流式输出，products和product_reason保持原样，按照业务事件为单位进行流式输出。