package com.ecomguide.repository

import com.ecomguide.model.ApiProduct
import com.ecomguide.model.FaqItem
import com.ecomguide.model.RagKnowledge
import com.ecomguide.model.ScenarioCard
import com.ecomguide.model.SkuOption
import com.ecomguide.model.UserReview

/**
 * 从 data/ecommerce_agent_dataset 提取的真实商品数据（演示用）
 * 图片通过 data_api.py 提供：http://10.0.2.2:8000/images/{image_path}
 */
object DemoProducts {

    // ─── 美妆护肤 ────────────────────────────────────────────────────────────────

    val beauty001 = ApiProduct(
        productId = "p_beauty_001",
        title = "雅诗兰黛特润修护肌活精华露 淡纹紧致抗初老精华30ml",
        brand = "雅诗兰黛", category = "美妆护肤", subCategory = "精华",
        basePrice = 720.0,
        imageUrl = "/images/1_美妆护肤/images/p_beauty_001_live.jpg",
        img = "https://picsum.photos/seed/p_beauty_001/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("容量" to "30ml 经典装"), 720.0),
            SkuOption("s2", mapOf("容量" to "50ml 加大装"), 980.0),
            SkuOption("s3", mapOf("容量" to "75ml 家用装"), 1260.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "雅诗兰黛特润修护肌活精华露（小棕瓶）是品牌经典抗初老单品，主打夜间肌底修护。核心成分含高浓度二裂酵母发酵产物溶胞物，能深入修护日间紫外线、污染造成的损伤，促进肌肤代谢；搭配透明质酸锁水保湿，猴面包树籽提取物淡纹紧致。适合25+有干纹细纹、熬夜后暗沉的抗初老人群，建议每晚洁面爽肤后取3-4滴掌心温热，轻按面部至吸收。",
            officialFaq = listOf(
                FaqItem("核心成分二裂酵母有什么作用？", "二裂酵母发酵产物溶胞物能模拟皮肤微生态，帮助修护日间紫外线、污染等外界刺激造成的肌底损伤，促进肌肤新陈代谢，增强皮肤屏障功能，长期使用可改善皮肤稳定性和细腻度。"),
                FaqItem("30ml、50ml、75ml怎么选？", "30ml适合初次尝试或出差携带；50ml性价比更高，适合日常长期使用；75ml最实惠，适合老用户囤货或家庭多人共用。"),
                FaqItem("适合敏感肌吗？", "大部分肤质适用，但敏感肌需谨慎。建议先在耳后测试24小时，无不适再正常使用。开封后6个月内用完，避免阳光直射存放。")
            ),
            userReviews = listOf(
                UserReview("李小米", 1, "用了两次就脸颊泛红刺痛，敏感肌不适合这款，早知道先测试，浪费了。"),
                UserReview("王梓涵", 2, "用了快一个月，保湿还行，但淡纹紧致完全没效果，性价比太低。"),
                UserReview("张雅静", 5, "熬夜党救星！每晚3滴吸收超快不黏腻，半个月后眼角干纹淡了，已回购50ml！"),
                UserReview("刘梦琪", 2, "用了三周除了保湿没别的效果，抗初老根本没感觉，有点失望。"),
                UserReview("陈宇飞", 1, "混油皮用了反而更干还冒闭口，这款不适合混油皮，后悔买了。")
            )
        )
    )

    val beauty002 = ApiProduct(
        productId = "p_beauty_002",
        title = "兰蔻小黑瓶全新精华肌底液 修护维稳提亮肤色30ml",
        brand = "兰蔻", category = "美妆护肤", subCategory = "精华",
        basePrice = 760.0,
        imageUrl = "/images/1_美妆护肤/images/p_beauty_002_live.jpg",
        img = "https://picsum.photos/seed/p_beauty_002/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("容量" to "30ml 标准装"), 760.0),
            SkuOption("s2", mapOf("容量" to "50ml 加大装"), 1080.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "兰蔻小黑瓶精华肌底液核心成分含98%高纯度二裂酵母发酵产物溶胞物，搭配益生元复合物，能深入肌底修护受损屏障，强韧肌肤抵御力。适合25+初抗老、肤色暗沉、熬夜后皮肤状态差的人群。",
            officialFaq = listOf(
                FaqItem("小黑瓶使用顺序怎么排？", "爽肤水之后、面霜之前使用，可提升后续护肤品的吸收效率，通常被称为「底妆前精华」，能让后续产品吸收更快。"),
                FaqItem("与小棕瓶有什么区别？", "小黑瓶更侧重肌底修护和提亮，功效较均衡；小棕瓶更专注于夜间深层修护和抗老。可根据自身需求选择。")
            ),
            userReviews = listOf(
                UserReview("周悦然", 5, "肌底液名不虚传，用完后续面霜吸收快很多，皮肤通透了！"),
                UserReview("吴思远", 3, "效果不如预期，保湿可以但抗老没感觉，价格偏高。"),
                UserReview("林晓雪", 4, "用了一个月，皮肤确实变细腻了，毛孔也小了一点，回购中。"),
                UserReview("赵明宇", 1, "过敏了，第二天脸上起了小疙瘩，不适合我的肤质。"),
                UserReview("陈思雨", 3, "味道有点奇怪，效果一般，不会再购了。"),
                UserReview("王浩然", 4, "性价比还行，配合面膜使用效果更好。")
            )
        )
    )

    val beauty004 = ApiProduct(
        productId = "p_beauty_004",
        title = "资生堂新红妍肌活精华露 红腰子修护维稳精华50ml",
        brand = "资生堂", category = "美妆护肤", subCategory = "精华",
        basePrice = 590.0,
        imageUrl = "/images/1_美妆护肤/images/p_beauty_004_live.jpg",
        img = "https://picsum.photos/seed/p_beauty_004/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("容量" to "30ml 经典装"), 590.0),
            SkuOption("s2", mapOf("容量" to "50ml 加大装"), 860.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "资生堂新红妍肌活精华露（红腰子）核心含ULTIMUNE肌活复合物，能激活肌肤自身防御机制，强韧肌底。添加保加利亚玫瑰水与透明质酸，兼顾舒缓与保湿。适合换季敏感、屏障受损、需要维稳的人群。",
            officialFaq = listOf(
                FaqItem("红腰子适合什么肤质？", "全肤质适用，尤其换季容易泛红、敏感、肌底薄弱的人群效果明显。"),
                FaqItem("和小棕瓶/小黑瓶有什么区别？", "红腰子主打屏障修护和维稳，更适合需要打底提升肌肤免疫力的人；价格也相对亲民，是入门级精华首选。")
            ),
            userReviews = listOf(
                UserReview("林小雨", 5, "换季必备！用了之后脸不泛红了，皮肤稳定很多，一直回购。"),
                UserReview("赵天明", 4, "质地水润好吸收，维稳效果明显，就是价格略贵。"),
                UserReview("孙佳佳", 2, "用了两周没什么明显变化，可能不适合我的肤质。")
            )
        )
    )

    // ─── 数码电子 ─────────────────────────────────────────────────────────────────

    val digital007 = ApiProduct(
        productId = "p_digital_007",
        title = "华为 FreeBuds Pro 5 主动降噪真无线蓝牙耳机 旗舰音质",
        brand = "华为", category = "数码电子", subCategory = "真无线耳机",
        basePrice = 1699.0,
        imageUrl = "/images/2_数码电子/images/p_digital_007_live.jpg",
        img = "https://picsum.photos/seed/p_digital_007/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("版本" to "标准版", "颜色" to "典雅黑"), 1699.0),
            SkuOption("s2", mapOf("版本" to "标准版", "颜色" to "冰霜银"), 1699.0),
            SkuOption("s3", mapOf("版本" to "高阶版", "颜色" to "典雅黑"), 1899.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "华为FreeBuds Pro 5搭载超感知主动降噪系统，最高降噪深度可达-50dB，支持3麦克风通话降噪。内置旗舰级11mm动圈+平衡电枢三单元复合发声系统，支持LDAC和LHDC 5.0高清音频传输，单次续航6小时。",
            officialFaq = listOf(
                FaqItem("FreeBuds Pro 5和5代之前有什么升级？", "主要升级点：降噪深度提升至-50dB、新增心率健康监测、续航提升10%、支持LHDC 5.0传输协议。"),
                FaqItem("连接安卓和苹果设备有区别吗？", "华为耳机与EMUI/HarmonyOS设备配合更流畅，可享受低延迟和自动切换功能；与iOS设备也可正常配对使用，但部分高级功能受限。")
            ),
            userReviews = listOf(
                UserReview("科技宅小明", 5, "降噪效果真的强！地铁上完全沉浸，外放也很好听，华为这次发挥正常了。"),
                UserReview("音乐发烧友", 4, "音质比上代提升明显，三频均衡，但高频稍微有点刺耳，建议煲机。"),
                UserReview("通勤达人", 3, "降噪不错，但App功能有点复杂，新手上手需要时间。"),
                UserReview("王小花", 2, "跟iPhone配对时偶尔断连，希望固件能修复。"),
                UserReview("运动党", 4, "运动时稳固不掉，防汗防水表现很好，推荐。")
            )
        )
    )

    val digital018 = ApiProduct(
        productId = "p_digital_018",
        title = "Apple AirPods Pro 3 主动降噪真无线耳机 心率监测版",
        brand = "Apple 苹果", category = "数码电子", subCategory = "真无线耳机",
        basePrice = 1899.0,
        imageUrl = "/images/2_数码电子/images/p_digital_018_live.jpg",
        img = "https://picsum.photos/seed/p_digital_018/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("版本" to "标准版", "充电盒" to "MagSafe充电盒"), 1899.0),
            SkuOption("s2", mapOf("版本" to "含AppleCare+", "充电盒" to "MagSafe充电盒"), 2199.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "AirPods Pro 3新增耳腔式精准心率传感模块，搭配升级的自适应主动降噪功能，最高可抵消48dB环境噪音。支持空间音频头部追踪，与Apple设备无缝切换，H3芯片带来更低延迟和更长续航（单次7h）。",
            officialFaq = listOf(
                FaqItem("AirPods Pro 3适合非苹果用户吗？", "可以配对安卓使用，但自动切换、Siri、心率监测和空间音频等功能仅在Apple设备上可用，非苹果用户体验会大打折扣。"),
                FaqItem("和Pro 2的核心区别是什么？", "新增心率监测、H3芯片性能提升20%、单次续航从6h提升至7h、降噪深度从40dB提升至48dB。")
            ),
            userReviews = listOf(
                UserReview("果粉小王", 5, "苹果全家桶必备，切换设备太丝滑了，降噪给力，心率功能很实用！"),
                UserReview("运动健身控", 4, "配合Apple Watch监测运动数据很方便，佩戴舒适，就是价格有点贵。"),
                UserReview("音乐人", 3, "音质对比同价位差一些，但胜在生态完善，苹果用户还是推荐。"),
                UserReview("商务人士", 5, "通话降噪极好，会议室效果杠杠的，一键接听非常方便。"),
                UserReview("吃瓜群众", 2, "价格太贵了，同价位可以买到更好音质的耳机，主要是为生态买单。")
            )
        )
    )

    // ─── 运动跑鞋 ─────────────────────────────────────────────────────────────────

    val clothes007 = ApiProduct(
        productId = "p_clothes_007",
        title = "Nike Air Zoom Pegasus 41 男子缓震跑步鞋 日常训练公路跑",
        brand = "耐克", category = "服饰运动", subCategory = "跑步鞋",
        basePrice = 899.0,
        imageUrl = "/images/3_服饰运动/images/p_clothes_007_live.jpg",
        img = "https://picsum.photos/seed/p_clothes_007/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("款型" to "男款", "尺码" to "39码"), 899.0),
            SkuOption("s2", mapOf("款型" to "男款", "尺码" to "40码"), 899.0),
            SkuOption("s3", mapOf("款型" to "男款", "尺码" to "41码"), 899.0),
            SkuOption("s4", mapOf("款型" to "男款", "尺码" to "42码"), 899.0),
            SkuOption("s5", mapOf("款型" to "女款", "尺码" to "36码"), 899.0),
            SkuOption("s6", mapOf("款型" to "女款", "尺码" to "37码"), 899.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "Nike Air Zoom Pegasus 41搭载前后掌分离式Zoom Air气垫，搭配全掌ReactX泡棉中底，脚感轻弹有支撑。重量约为255g（男款41码），适合日常通勤、5-10km轻松跑和节奏跑，全路况适应性强。",
            officialFaq = listOf(
                FaqItem("飞马41和飞马40相比有什么升级？", "主要升级点：前掌Zoom Air气垫增大了20%，中底ReactX配比调整，脚感更柔软弹性更强，外底橡胶覆盖面积也有增加，耐磨性更好。"),
                FaqItem("尺码怎么选？偏大还是偏小？", "飞马系列偏标准，建议选择平时穿的尺码。脚型偏宽可以选宽楦版本，穿着会更舒适。"),
                FaqItem("适合马拉松比赛吗？", "飞马系列定位日常训练和慢跑，不适合马拉松比赛。比赛建议选择Nike Vaporfly或Alphafly等竞速跑鞋。")
            ),
            userReviews = listOf(
                UserReview("跑步爱好者", 5, "买来日常5km训练，脚感非常舒服，前掌zoom气垫弹性十足！"),
                UserReview("城市通勤族", 4, "作为日常通勤鞋颜值在线，穿着舒适，就是时间久了底部磨损较快。"),
                UserReview("健身达人", 4, "跑步和健身都能穿，性价比不错，耐克这双物超所值。"),
                UserReview("周末运动党", 3, "整体还可以，但感觉不如上一代贴脚，新款包覆感略差。")
            )
        )
    )

    val clothes009 = ApiProduct(
        productId = "p_clothes_009",
        title = "HOKA Clifton 9 男子缓震公路跑鞋 厚底回弹长距离训练",
        brand = "HOKA", category = "服饰运动", subCategory = "跑步鞋",
        basePrice = 1099.0,
        imageUrl = "/images/3_服饰运动/images/p_clothes_009_live.jpg",
        img = "https://picsum.photos/seed/p_clothes_009/400/400",
        skus = listOf(
            SkuOption("s1", mapOf("款型" to "男款", "颜色" to "经典黑", "尺码" to "40码"), 1099.0),
            SkuOption("s2", mapOf("款型" to "男款", "颜色" to "经典黑", "尺码" to "41码"), 1099.0),
            SkuOption("s3", mapOf("款型" to "男款", "颜色" to "白蓝", "尺码" to "40码"), 1099.0),
            SkuOption("s4", mapOf("款型" to "女款", "颜色" to "玫瑰粉", "尺码" to "36码"), 1099.0)
        ),
        ragKnowledge = RagKnowledge(
            marketingDescription = "HOKA Clifton 9全掌加厚EVA中底重量比前代轻了15%，踩踏软弹不塌，落地缓震感极佳，适合长距离日常训练。经典厚底设计深受慢跑者和长跑爱好者喜爱，提供出色的保护性和舒适性。",
            officialFaq = listOf(
                FaqItem("HOKA厚底鞋跑步稳定吗？", "Clifton 9的加宽鞋底和低落差（5mm）设计保证了良好的稳定性，非常适合长距离慢跑，但对于需要快速转向的运动（如篮球）不建议。"),
                FaqItem("适合初跑者吗？", "非常适合！厚底缓震保护膝盖，低落差鞋底帮助建立正确跑姿，是初跑者和长跑者的理想选择。")
            ),
            userReviews = listOf(
                UserReview("长跑爱好者", 5, "HOKA厚底真的太舒服了，跑10km毫无压力，脚感像踩云朵！"),
                UserReview("保膝党", 4, "膝盖不好选HOKA没错，缓震很好，就是比较重，短跑不适合。"),
                UserReview("初跑者小刘", 4, "新手首选，穿着很舒服，跑步不累腿，颜值也在线。"),
                UserReview("专业跑者", 3, "长距离训练不错，但比起竞速款反馈感不足，看需求选择。"),
                UserReview("日常散步族", 5, "用来散步简直神了，走了8公里脚一点都不酸！")
            )
        )
    )

    // ─── 分组方便查询 ──────────────────────────────────────────────────────────────

    val beautyProducts = listOf(beauty001, beauty002, beauty004)
    val digitalProducts = listOf(digital007, digital018)
    val sportsProducts = listOf(clothes007, clothes009)
    val allProducts = beautyProducts + digitalProducts + sportsProducts

    fun findById(id: String): ApiProduct? = allProducts.find { it.productId == id }

    // ─── 场景推荐卡片（ScenarioCard）Mock 数据 ──────────────────────────────
    // 参考图3：聊天消息流中的品类入口形式

    /** 春日连衣裙场景 */
    val scenarioSpringDress = ScenarioCard(
        scenarioId = "scenario_spring_dress",
        scenarioName = "春日连衣裙",
        emoji = "🌸",
        subtitle = "（一件搞定懒人必备）",
        category = "服饰运动",
        products = listOf(clothes007, clothes009),
        firstProductTitle = "春游连衣裙",
        firstProductPrice = 143.90,
        firstProductImage = clothes007.imageUrl,
        productCount = 12,
        shopHint = "夕蒙seemon等多店在售"
    )

    /** 春游穿搭场景 */
    val scenarioSpringOutfit = ScenarioCard(
        scenarioId = "scenario_spring_outfit",
        scenarioName = "春游穿搭",
        emoji = "👗",
        subtitle = "（百搭耐看）",
        category = "服饰运动",
        products = listOf(clothes007, clothes009),
        firstProductTitle = "春游百搭上衣",
        firstProductPrice = 38.20,
        firstProductImage = clothes009.imageUrl,
        productCount = 8,
        shopHint = "韩妮彩o等多店在售"
    )

    /** 抗初老精华场景 */
    val scenarioAntiAging = ScenarioCard(
        scenarioId = "scenario_anti_aging",
        scenarioName = "抗初老精华",
        emoji = "✨",
        subtitle = "（不用纠结 直接抄）",
        category = "美妆护肤",
        products = beautyProducts,
        firstProductTitle = "小棕瓶精华露",
        firstProductPrice = 720.0,
        firstProductImage = beauty001.imageUrl,
        productCount = 6,
        shopHint = "雅诗兰黛官方旗舰店在售"
    )

    /** 降噪耳机场景 */
    val scenarioHeadphone = ScenarioCard(
        scenarioId = "scenario_headphone",
        scenarioName = "旗舰降噪耳机",
        emoji = "🎧",
        subtitle = "（音质天花板）",
        category = "数码电子",
        products = digitalProducts,
        firstProductTitle = "AirPods Pro 3",
        firstProductPrice = 1899.0,
        firstProductImage = digital018.imageUrl,
        productCount = 5,
        shopHint = "苹果官方旗舰店在售"
    )

    /** 所有场景卡片列表 */
    val allScenarioCards = listOf(
        scenarioSpringDress,
        scenarioSpringOutfit,
        scenarioAntiAging,
        scenarioHeadphone
    )
}
