# 依赖清单

本文件列出项目所有模块的依赖项及版本号，供依赖审查和环境复现使用。

---

## 后端（server/）

**运行环境：** Python 3.9+

**依赖文件（权威来源）：** [`server/requirements.txt`](server/requirements.txt)

```bash
cd server
python3 -m pip install -r requirements.txt
```

> 各依赖包的版本号见 `requirements.txt`，以下仅说明用途：

| 依赖包 | 用途 |
|--------|------|
| fastapi | Web 框架，提供 REST API 和 SSE 流式接口 |
| uvicorn | ASGI 服务器，运行 FastAPI 应用 |
| aiofiles | 异步文件读取（图片静态文件服务） |
| pydantic / pydantic-settings | 数据校验与序列化，从 .env 加载配置 |
| httpx | 异步 HTTP 客户端（LLM API 调用） |
| volcengine-python-sdk | 火山引擎 Ark SDK（Doubao LLM 接入，预留） |
| chromadb | 向量数据库（RAG 语义检索，预留） |
| python-dotenv | 加载 .env 环境变量文件 |
| pytest | 单元测试框架 |

---

## Android 客户端（client/）

**依赖文件：** `client/app/build.gradle.kts`

### 构建环境

| 工具 | 版本 | 说明 |
|------|------|------|
| Android Studio | Hedgehog (2023.1.1)+ | IDE，含 JBR |
| JDK | 17 | `kotlinOptions.jvmTarget = "17"`，Android Studio 自带 JBR 满足 |
| Gradle | 8.5 | Gradle Wrapper（`gradle-wrapper.properties`） |
| AGP（Android Gradle Plugin）| 8.3.2 | `client/build.gradle.kts` |
| Kotlin | 1.9.23 | `client/build.gradle.kts` |
| compileSdk | 34 | Android 14 |
| minSdk | 26 | Android 8.0（Oreo） |
| targetSdk | 34 | Android 14 |

### Gradle 插件

| 插件 | 说明 |
|------|------|
| `com.android.application` | Android 应用构建 |
| `org.jetbrains.kotlin.android` | Kotlin Android 支持 |
| `kotlin-parcelize` | 自动生成 Parcelable 实现（用于 ApiProduct、CartItem 在 Intent 间传递）|

### AndroidX & UI

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| androidx.core:core-ktx | 1.12.0 | Kotlin 扩展函数 |
| androidx.appcompat:appcompat | 1.6.1 | 向后兼容 Activity/Fragment |
| androidx.activity:activity-ktx | 1.8.2 | `viewModels()` 委托属性 |
| androidx.fragment:fragment-ktx | 1.6.2 | `activityViewModels()` 委托属性 |
| com.google.android.material:material | 1.11.0 | Material Design 3 组件（Chip、CardView 等） |
| androidx.constraintlayout:constraintlayout | 2.1.4 | 约束布局 |
| androidx.recyclerview:recyclerview | 1.3.2 | 消息列表、商品卡片列表 |
| androidx.cardview:cardview | 1.0.0 | 商品卡片容器 |

### 导航

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| androidx.navigation:navigation-fragment-ktx | 2.7.6 | Fragment 导航 |
| androidx.navigation:navigation-ui-ktx | 2.7.6 | 导航栏联动 |

### 生命周期

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| androidx.lifecycle:lifecycle-viewmodel-ktx | 2.7.0 | ViewModel + 协程支持 |
| androidx.lifecycle:lifecycle-livedata-ktx | 2.7.0 | LiveData 观察者 |
| androidx.lifecycle:lifecycle-runtime-ktx | 2.7.0 | lifecycleScope 协程作用域 |

### 网络

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| com.squareup.retrofit2:retrofit | 2.9.0 | REST API 客户端 |
| com.squareup.retrofit2:converter-gson | 2.9.0 | JSON 反序列化 |
| com.squareup.okhttp3:okhttp | 4.12.0 | HTTP 客户端（含 SSE 流式读取） |
| com.squareup.okhttp3:logging-interceptor | 4.12.0 | 网络日志（Debug 模式） |

### 图片

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| com.github.bumptech.glide:glide | 4.16.0 | 图片异步加载、缓存、错误 fallback |

### 协程

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| org.jetbrains.kotlinx:kotlinx-coroutines-android | 1.7.3 | 协程 Android 支持（lifecycleScope） |

### 测试

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| junit:junit | 4.13.2 | 单元测试 |
| androidx.test.ext:junit | 1.1.5 | Android JUnit 扩展 |
| androidx.test.espresso:espresso-core | 3.5.1 | UI 自动化测试 |

---

## 大模型 API

| 配置项 | 值 |
|--------|-----|
| 模型 | Doubao-Seed-2.0-lite |
| 端点 | `ep-20260514111645-lmgt2` |
| Base URL | `https://ark.cn-beijing.volces.com/api/v3/` |
| 配置文件 | `server/.env`（不提交 Git，见 .gitignore） |
