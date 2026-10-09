# 立面智能体（facade_agent）

用 **LangGraph 主管图 + 建模子图 + MCP 工具层** 驱动 Rhino，把「效果图 → 可调整的三维立面构件」串成一条可复现、可核对、可中断的流程。

版本：0.1.0 ｜ 运行环境：VS Code + Python 3.11+ ｜ Rhino：8（官方 MCP：`MCPConnect`）

---

## 0. 一句话说明它解决什么

| 老问题 | 本项目的做法 |
|---|---|
| AI 出的立面图**有偏差** | 几何不由 AI 画，由程序按模型真实尺寸算 |
| 贴上去的图**不能调整** | 交付的是**参数化构件**（可选中、可拖动、可改参数重跑） |
| 智能体**不知道自己做得对不对** | **测量裁判**（覆盖率 / 偏移 / 洞口冲突）说了算，不靠智能体自我评价 |

---

## 1. 三层架构

```
        ┌──── 编排层（LangGraph，本项目）────┐
        │  主管图：读图 → 出方案 → 选图 → 转译 → 建模 → 确认 → 冻结  │
        │  建模子图：规划 → 执行 → 测量 →（不达标）修正 → 上限交人工  │
        └──────────────────┬──────────────────────────────────────┘
                           ▼
              MCP 工具层（facade 自建 + Rhino 官方）
                           ▼
                 Rhino 8（真 NURBS 几何）
```

**分工**：编排层管"下一步做什么"，工具层管"怎么做"，测量管"做对没有"。

---

## 2. 目录结构

```
facade_agent/
├── README.md                     ← 你正在看的
├── requirements.txt              依赖
├── .env.example                  配置模板（复制成 .env）
├── .vscode/launch.json           5 个调试配置，F5 直接用
├── facade_agent/
│   ├── __init__.py               包入口（导入 tools 触发注册）
│   ├── config.py                 配置：全项目唯一来源
│   ├── state.py                  状态：两张图的契约
│   ├── llm.py                    模型：换模型只改这里
│   ├── registry.py               注册表：构件类型 / 测量指标（开闭原则落点）
│   ├── mcp_client.py             MCP 接入：唯一与 MCP 打交道的地方
│   ├── cli.py                    命令行入口
│   ├── tools/
│   │   ├── component_builders.py 构件实现（竖向格栅、腰线…）
│   │   └── measure_tools.py      测量指标 + 给智能体的"眼睛"
│   ├── nodes/
│   │   ├── build.py              建模子图三节点（规划 / 执行 / 测量）
│   │   └── main.py               主管图节点（读图 / 出方案 / 转译 / 冻结 / 报告）
│   └── graphs/
│       ├── build_subgraph.py     建模子图
│       └── main_graph.py         主管图
└── tests/
    ├── test_registry_and_measures.py   注册表与指标（6 项）
    └── test_graph_smoke.py             图结构与闭环（4 项）
```

---

## 3. 快速开始（VS Code，7 步）

### 第 1 步：打开项目
VS Code → 打开文件夹 → 选择 `facade_agent` 目录。

### 第 2 步：建虚拟环境
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```
VS Code 右下角选解释器 → 选 `.venv`。

### 第 3 步：装依赖
```bash
pip install -r requirements.txt
```

### 第 4 步：建配置文件
```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```
打开 `.env`，**只改三行**：
```
FACADE_WORKSPACE=D:/你的Rhino工作区目录
LLM_API_KEY=sk-你的密钥
LLM_BASE_URL=https://api.a6api.com/v1
```

### 第 5 步：跑自检（不花额度）
按 **F5** → 选 **「1 · 自检（不花额度）」**，或在终端跑：
```bash
python -m facade_agent.cli --check
```
**期望看到**：注册表 2 构件 + 3 指标、两张图编译通过、MCP 状态。

### 第 6 步：离线跑通闭环（不需要 Rhino、不需要密钥）
```bash
python -m facade_agent.cli --demo
```
**期望看到**：
```
规划：16 个构件，20 条规律线
指标：conflicts = 0.0  coverage = 1.0  rhythm_dev = 0.0
判定：ok  轮次 1
```
这一步证明「规划 → 执行 → 测量 → 判定」这条闭环是通的。

### 第 7 步：跑主管图全流程
```bash
python -m facade_agent.cli --run --offline
```
**期望看到**：`报告 立面 ELEV_S：生成构件 6 个，迭代 1 轮，覆盖率 1.000，洞口冲突 0.000。已达标，可交付。`

---

## 4. 跑测试

```bash
python tests/test_registry_and_measures.py     # 6 项
python tests/test_graph_smoke.py               # 4 项
```
在 VS Code 里也可以：打开测试文件 → F5 → 选「5 · 当前测试文件」。

---

## 5. 接 MCP（从离线切到在线）

### 5.1 启动 Rhino 官方 MCP
1. 打开 Rhino 8；
2. 命令行输入 `MCPConnect`（在 Rhino 里启动 MCP 服务）；
3. 记下它提示的端口（默认 `127.0.0.1:1999`）。

### 5.2 在 `.env` 里填 MCP 命令
```ini
RHINO_MCP_COMMAND=uvx
RHINO_MCP_ARGS=["rhinomcp@latest"]
FACADE_MCP_COMMAND=python
FACADE_MCP_ARGS=["-m","facade_mcp_server"]
FACADE_OFFLINE=false
```
> `FACADE_OFFLINE=false` 是切到在线的开关。

### 5.3 验证
```bash
python -m facade_agent.cli --check
```
看 `[3] MCP 连接` 一节：`模式 online ｜ 工具 N`，并列出工具名。

**安全说明**：`mcp_client.py` 里有 `RHINO_TOOL_ALLOWLIST`——官方 MCP 暴露了"执行任意代码"的能力，**只有白名单里的工具会交给智能体**，其余一律过滤掉。

---

## 6. 建议的代码阅读顺序（一步步）

| 顺序 | 文件 | 看什么 |
|---|---|---|
| 1 | `facade_agent/state.py` | 两张图的**数据契约**——先搞清楚流转的是什么 |
| 2 | `facade_agent/registry.py` | **注册表机制**——本项目最重要的设计，开闭原则的落点 |
| 3 | `facade_agent/tools/component_builders.py` | 构件怎么从参数展开成几何 |
| 4 | `facade_agent/tools/measure_tools.py` | **测量裁判**——为什么它比"智能体自我判断"可靠 |
| 5 | `facade_agent/nodes/build.py` | 三个节点：规划（计算）/ 执行（智能体）/ 测量（裁判） |
| 6 | `facade_agent/graphs/build_subgraph.py` | 子图怎么连，条件边怎么走 |
| 7 | `facade_agent/nodes/main.py` | 主管图节点，每个都有离线分支 |
| 8 | `facade_agent/graphs/main_graph.py` | 主管图 + 子图嵌套 + 中断点 |
| 9 | `facade_agent/mcp_client.py` | MCP 接入与白名单 |
| 10 | `facade_agent/config.py` / `llm.py` | 配置与模型 |

---

## 7. 扩展点（改什么、不改什么）

| 想加什么 | 改哪里 | 不用改什么 |
|---|---|---|
| **一种新构件**（如曲面雨棚） | `tools/component_builders.py` 加一个 `@register_component` 函数 | 图、节点、测量、配置 |
| **一个新指标**（如垂直度） | `tools/measure_tools.py` 加一个 `@register_measure` 函数 | 图、节点、构件 |
| **换模型** | `.env` 的 `MODEL_MAIN` / `MODEL_BUILD`，或 `llm.py` | 其它全部 |
| **换智能体实现**（如 deepseek-harness） | `nodes/build.py` 的 `make_act_node` | 两张图、其它节点 |
| **加流程节点** | `nodes/main.py` 加函数 + `graphs/main_graph.py` 加两条边 | 子图、工具 |
| **改达标线** | `.env` 的 `COVERAGE_TARGET`，或 `registry.py` 的 `target` | 代码逻辑 |

---

## 8. 当前实现状态（诚实标注）

| 部分 | 状态 |
|---|---|
| 配置 / 状态 / 注册表 / 测量 / 两张图 | ✅ 已跑通（沙箱实测，10 项测试全过） |
| 离线闭环（规划→执行→测量→判定→交人工） | ✅ 已验证 |
| 构件类型（竖向格栅、腰线） | ✅ 基础实现，可扩展 |
| MCP 在线路径 | ⚠️ 代码就绪，**待你在本机接上 Rhino 验证** |
| 读参考图 / 转译（LLM 节点） | ⚠️ 代码就绪，**待你在本机配好密钥后验证** |
| 冻结（需人工确认） | ⚠️ 中断点已接好，**待接上 facade MCP 工具后验证** |

---

## 9. 常见问题

**Q：`--check` 报注册表为空？**
A：说明 `facade_agent/tools/` 没被导入。检查 `facade_agent/__init__.py` 里有没有 `from . import tools`。

**Q：`--run` 停在中途不动了？**
A：那是 `freeze` 的中断点生效了（正常）。它需要 checkpointer 才能恢复；用 `build_graph_with_sqlite()` 编译图即可「关电脑明天接着跑」。

**Q：想先看流程对不对，但还没接 Rhino？**
A：`FACADE_OFFLINE=true` 就是为这个准备的——全部节点走确定性分支，图照样跑完。

**Q：智能体乱调工具怎么办？**
A：三层护栏：① `RHINO_TOOL_ALLOWLIST` 白名单；② 构件参数由 `registry` 校验；③ 冻结/删除类操作在图上设中断点，必须人工确认。