# AI-Agent-Ecom-Guide

> 基于 RAG 的多模态电商智能导购 AI Agent

## 项目简介

本项目是一个**AI 驱动的电商智能导购系统**，利用 RAG（检索增强生成）技术结合豆包大模型，为用户提供智能化的商品推荐与购物咨询服务。系统支持多模态交互（文本/图片），能够理解用户意图、检索商品知识库，并生成精准的导购建议。

## 技术选型

| 层级 | 技术 | 说明 |
|------|------|------|
| 移动端（客户端） | Android + Kotlin | 原生 Android 开发，使用 Jetpack 组件与 Retrofit 网络框架 |
| 后端服务 | Python + FastAPI | 高性能异步 API 服务，负责业务逻辑与大模型调用 |
| 大模型 | 豆包大模型（火山引擎） | 提供自然语言理解与生成能力，通过 RAG 增强商品知识检索 |
| 向量数据库 | ChromaDB / FAISS | 存储商品知识库的向量索引，支持语义检索 |

## 项目结构

```
AI-Agent-Ecom-Guide/
├── client/                  # Android 客户端（Kotlin）
│   └── app/
│       └── src/main/java/com/ecomguide/
│           ├── ui/          # UI 层 — Activity、Fragment、Adapter
│           ├── network/     # 网络层 — Retrofit 客户端与 API 接口定义
│           └── model/       # 数据模型层 — 实体类与数据结构
├── server/                  # 后端服务（Python FastAPI）
│   └── app/
│       ├── api/             # API 路由层
│       ├── core/            # 核心配置与中间件
│       ├── models/          # 数据模型
│       └── services/        # 业务逻辑层（RAG 检索、大模型调用）
└── docs/                    # 项目文档
    ├── api/                 # API 接口文档
    ├── design/              # 设计文档与架构图
    └── minutes/             # 小组会议记录
```

## 👥 团队协作与分工

* **周宝怡 (App 核心架构开发负责人)**：
  - 负责项目本地工程地基初始化、Android 原生多层目录规范规范（UI/Network/Model）的搭建。
  - 主导客户端核心框架开发，负责流式渲染架构设计、端到端网络通信连接以及移动端状态管理。

* **孙煊茗 (前端 UI 与交互开发负责人)**：
  - 负责多模态智能导购 App 的主界面、流式聊天气泡窗口以及动态商品卡片的 UI 视觉呈现。
  - 负责前端用户交互逻辑优化、提示词（Prompt）工程的客户端对接，提升导购助手的用户体验。

* **杨莫凡 (后端架构与大模型基础设施负责人)**：
  - 负责基于 FastAPI 的高并发后端服务搭建，打通与豆包大模型（Doubao-Seed-2.0-lite）的流式 API 接口。
  - 负责电商 RAG（检索增强生成）知识库建设、向量数据库初始化以及召回优化。

## 快速开始

### 后端服务

```bash
cd server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Android 客户端

1. 使用 Android Studio 打开 `client/` 目录
2. 同步 Gradle 依赖
3. 运行到模拟器或真机

## 许可证

本项目仅供课程学习使用。
