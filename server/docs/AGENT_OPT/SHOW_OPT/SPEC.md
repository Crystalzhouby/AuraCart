# 变动/api/search接口的返回数据

## 单品类查询返回

当前的单品类查询返回的数据：
输出检索到的多件商品，然后返回一大段推荐理由推荐多件商品，然后返回done，最后返回三个选项。
如下所示：
```
event: products
data: [{"product_id":"p_digi_001","sku_id":"s_p_digi_001_1","category":"数码电子","sub_category":"蓝牙耳机"},{"product_id":"p_digi_002","sku_id":"s_p_digi_002_1","category":"数码电子","sub_category":"蓝牙耳机"}]

event: chat_reply
data: "为您找到 2 款 200 元以内的蓝牙耳机：\n1. 漫步者 X3——¥159..."

event: done
data: {"next_options_count":3,"conversation_id":"550e8400-..."}

event: next_options
data: ["需要关注降噪功能吗？","想看看 100 元以内的入门款吗？","比较一下这几款"]
```

现改动为：
首先在extraction节点，根据检索到的用户意图输出一段欢迎语。
然后进入retrival节点根据用户意图检索商品。
先输出第一件商品，然后给出推荐第一件商品的推荐理由；
然后输出第二件商品，给出推荐第二件商品的推荐理由；
...以此类推，直至所有检索到的商品都输出了
输出done，现在需要额外输出一段结束语，“如有看中的款吗？或者告诉我你的肤质和预算，帮你再精准挑～”；
最后返回三个下一步的推荐选项。
如下所示：

```
# 用户查询：推荐几款蓝牙耳机。
event: welcome
data : "不含酒精的防晒霜对敏感肌超友好！帮你挑了几款口碑好、温和不刺激的。"

event: products
data: {"product_id":"p_digi_001","sku_id":"s_p_digi_001_1","category":"数码电子","sub_category":"真无线耳机"}

event: chat_reply
data: "漫步者 X3——¥159是一款高音质蓝牙耳机，..."

event: products
data: {"product_id":"p_digi_002","sku_id":"s_p_digi_002_1","category":"数码电子","sub_category":"真无线耳机"}

event: chat_reply
data: "小米buds是一款轻量式蓝牙耳机，..."

event: done
data: {"next_options_count":3,"conversation_id":"550e8400-...","text","有看中的款吗？或者告诉我你的肤质和预算，帮你再精准挑。"}

event: next_options
data: ["需要关注降噪功能吗？","想看看 100 元以内的入门款吗？","比较一下这几款"]
```

## 多品类查询返回

现有版本返回数据方案，例子如下：
```
event: products
data: [{"product_id":"p_beauty_001","sku_id":"s_p_beauty_001_1","category":"美妆护肤","sub_category":"防晒"},...]

event: chat_reply
data: "为您推荐以下防晒霜：\n1. 安热沙小金瓶——SPF50+..."

event: products
data: [{"product_id":"p_fash_010","sku_id":"s_p_fash_010_1","category":"服饰运动","sub_category":"墨镜"},...]

event: chat_reply
data: "墨镜方面，推荐：\n1. 雷朋飞行员系列——偏光防紫外线..."

event: products
data: [...]     ← 沙滩裤

event: chat_reply
data: "..."     ← 沙滩裤推荐理由

... (遮阳帽、凉鞋同理，按品类顺序依次发送)

event: done
data: {"next_options_count":2,"conversation_id":"550e8400-..."}

event: next_options
data: ["需要推荐泳衣吗？","需要搭配晒后修复产品吗？"]
```

新版本返回数据改进方案：

现改动为：
首先在scenario_gen节点，根据检索到的用户意图输出一段欢迎语。
然后进入retrival节点根据用户意图检索商品。
    先处理第一个推荐的品类，输出一段该品类的欢迎语，
    先输出该品类下的第一件商品，然后给出推荐第一件商品的推荐理由；
    然后输出该品类下的第二件商品，给出推荐第二件商品的推荐理由；
    ...以此类推，直至所有检索到的第一个品类下商品都输出了；
    再处理第二个推荐的品类，输出一段该品类的欢迎语，
    先输出该品类下的第一件商品，然后给出推荐第一件商品的推荐理由；
    然后输出该品类下的第二件商品，给出推荐第二件商品的推荐理由；
    ...以此类推，直至所有检索到的第二个品类下商品都输出了；
    再处理第三个推荐的品类，输出一段该品类的欢迎语，
    先输出该品类下的第一件商品，然后给出推荐第一件商品的推荐理由；
    然后输出该品类下的第二件商品，给出推荐第二件商品的推荐理由；
    ...以此类推，直至所有检索到的第三个品类下商品都输出了；
...以此类推，直至所有提取出的品类都输出了；
输出done，现在需要额外基于总体推荐的商品生成一段结束语，“以上就是为你搭配的海边出游三件套，有看中的款式吗？或者告诉我你的预算，帮你再进一步筛选～”；
最后返回三个下一步的推荐选项。

例子如下：

```
# 用户查询：去海边玩，推荐一下防晒霜、墨镜和沙滩裤。

event: welcome
data: "海边度假装备得备齐！结合你的出游场景，帮你整理了几个超实用的海边游玩必备品类～"

event: chat_reply
data: "🧴 首先是美妆护肤（防晒必备）。海边紫外线强，高倍数且防水的防晒必不可少："

event: products
data: {"product_id":"p_beauty_006","sku_id":"s_p_beauty_006_1","category":"美妆护肤","sub_category":"防晒"}

event: chat_reply
data: "巴黎欧莱雅主打水感轻薄质地，上脸瞬间推开成膜，无厚重黏腻感，适合海边游玩用。"

event: products
data: {"product_id":"p_beauty_010","sku_id":"s_p_beauty_010_1","category":"美妆护肤","sub_category":"防晒"}

event: chat_reply
data: "安热沙小金瓶——SPF50+，遇水防晒力更强，去海边冲浪游泳都不怕被晒黑！"

event: chat_reply
data: "\n\n🕶️ 接下来是服饰配件（凹造型加防晒）。除了涂抹防晒，物理防晒也很重要，选一件酷酷的短袖拍照更出片："

event: products
data: {"product_id":"p_clothes_001","sku_id":"s_p_clothes_001_2","category":"服饰运动","sub_category":"短袖T恤"}

event: chat_reply
data: "这款白色优衣库T恤吸湿速干效果好，出了汗也不会黏在背上，适合夏天出行穿。"

event: chat_reply
data: "\n\n🩳 最后是海边穿搭（清凉舒适）。去海滩怎么能少了一条舒适速干的沙滩裤："

event: products
data: {"product_id":"p_clothes_023","sku_id":"s_p_clothes_023_1","category":"服饰运动","sub_category":"运动短裤"}

event: chat_reply
data: "速干运动短裤——面料轻盈透气，下水后干得极快，花色也很有夏日热带的氛围。"

event: done
data: {"next_options_count":3,"conversation_id":"550e8400-...","text":"以上就是为你搭配的海边出游三件套，有看中的款式吗？或者告诉我你的具体尺码偏好，帮你再进一步筛选～"}

event: next_options
data: ["需要推荐适合海边的凉鞋吗？","需要搭配晒后修复产品吗？","比较一下这两款防晒霜"]
```

## 改动方面
为实现以上效果，一方面需要调整数据输出的顺序，此外，还需要引入新的"欢迎词"，"结束语"的LLM生成功能。

## 杂项
1.剔除提示词的冗余
在以下代码中，rewritten_query被传入了两次，注意其他LLM API调用是否也存在类似的情况。
```
prompt = (SCENARIO_GEN_SYSTEM
            .replace("{category_list}", category_list)
            .replace("{history_context}", history_context)
            .replace("{user_query}", rewritten_query))
messages = [
    {"role": "system", "content": prompt},
    {"role": "user", "content": rewritten_query},
]
```

