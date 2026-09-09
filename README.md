# Sentaurus MCP｜让 AI 助手调用 TCAD 仿真 

**中文** | [English](README.en.md)

**把准备输入、提交仿真、查看状态和读取日志，接入支持 MCP 的 AI 助手。**

面向已经使用 Sentaurus 的器件研究者。你可以让助手建立实验、提交已有脚本、查询运行进度，而不用在对话与终端之间反复复制信息。

> **当前版本：0.1 原型。** 已通过模拟任务测试，尚未验证真实 Sentaurus 执行。使用前需要自行安装 Sentaurus 并具备有效许可证。本仓库是独立工具，不包含私人科研工作台、器件结构或实验数据。

[能做什么](#能做什么) · [快速开始](#快速开始) · [怎么向助手提问](#怎么向助手提问) · [运行原理](#运行原理) · [常见问题](#常见问题) · [开发与验证](#开发与验证)

## 能做什么

| 你想完成的事 | 当前支持情况 |
| --- | --- |
| 保存输入脚本，建立一个实验 | 支持；记录输入文件指纹，提交前检查文件是否变化 |
| 提交 SDE、SDevice 或 SVisual 批处理任务 | 已实现调用入口；真实软件命令需在你的安装环境验证 |
| 同时提交多个实验 | 支持排队和最大并行数量设置；默认一次运行一个 |
| 查看当前及历史实验 | 支持查询状态、阶段、进程编号和耗时 |
| 查看求解日志 | 支持增量读取，避免每次传回整份日志 |
| 查看产生了哪些结果文件 | 支持文件清单；暂不解析 TDR 或自动绘图 |
| 关闭 AI 客户端后继续计算 | 独立后台执行器正常运行时，任务可继续 |
| 在 Sentaurus Workbench 中直接添加原生工程或实验 | **尚未实现**；当前保存的是批处理目录 |
| 自动判断收敛、提取击穿电压或优化器件参数 | **尚未实现** |
| 根据 CPU、内存和许可证自动排满资源 | **尚未实现**；目前只限制并行任务数 |
| 打包下载、取消任务、重启后自动恢复 | **尚未实现** |

## 快速开始

下面以 **在 Linux 仿真服务器上安装和运行** 为例。先完成服务器端配置，再连接 AI 客户端。

### 1. 准备环境

需要：

- Python 3.10 或以上版本。
- 已安装、可正常批处理运行的 Sentaurus 和有效许可证。
- 一个你有写入权限的数据目录。
- 支持 MCP 标准输入输出连接的客户端。

本工具不安装 Sentaurus，也不提供许可证。请先确认同一账号可以直接运行你的仿真脚本。

### 2. 下载并安装

```bash
git clone https://github.com/HanKin666/sentaurus-mcp.git
cd sentaurus-mcp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

仓库为私有时，下载账号需要仓库访问权限。

### 3. 配置仿真程序和数据目录

复制示例配置：

```bash
cp examples/config.example.json config.json
```

修改 `config.json`。以下路径都是占位示例，必须换成你自己的**绝对路径**：

```json
{
  "root": "/absolute/path/to/experiments",
  "max_parallel": 1,
  "tools": {
    "sde": ["/absolute/path/to/sde", "-e", "-l", "{input}"],
    "sdevice": ["/absolute/path/to/sdevice", "{input}"],
    "svisual": ["/absolute/path/to/svisual", "-b", "{input}"]
  }
}
```

| 配置项 | 含义 |
| --- | --- |
| `root` | 输入、结果、日志及实验索引的存储位置 |
| `max_parallel` | 最多同时运行多少个实验；不是每个实验的 CPU 核数 |
| `tools` | 允许调用的程序及其参数；需要核对本机 Sentaurus 版本 |
| `{input}` | 执行时自动替换为该阶段的输入文件名 |

许可证、运行库等环境变量沿用服务器已有设置。不要把账号、密码或私有配置提交到仓库。

### 4. 单独启动后台执行器

在一个独立终端中执行，路径替换为实际配置文件位置：

```bash
export SENTAURUS_MCP_CONFIG="/absolute/path/to/sentaurus-mcp/config.json"
sentaurus-worker
```

保持这个终端运行。长期使用时，可由服务器的服务管理器管理该进程。

**后台执行器负责排队和启动仿真，必须独立于 AI 客户端启动。** 不要让客户端在启动 MCP 时顺便启动它，否则客户端退出可能影响后台任务。

### 5. 连接 AI 客户端

下面是**客户端与 MCP 在同一台机器**时的通用 JSON 配置示例。具体配置文件位置和外层格式由客户端决定：

```json
{
  "mcpServers": {
    "sentaurus": {
      "command": "/absolute/path/to/sentaurus-mcp/.venv/bin/sentaurus-mcp",
      "env": {
        "SENTAURUS_MCP_CONFIG": "/absolute/path/to/sentaurus-mcp/config.json",
        "SENTAURUS_ENABLE_ACTIONS": "1"
      }
    }
  }
}
```

- `SENTAURUS_ENABLE_ACTIONS=1`：允许建立、提交实验。
- 改为 `0` 或不设置：只允许查询。
- MCP 和后台执行器必须使用同一个配置文件。
- 客户端在 Windows、Sentaurus 在 Linux 时，需要配置 SSH 标准输入输出连接，让 MCP 在服务器上运行；不能直接把服务器路径填成 Windows 本地命令。本版本暂未提供自动配置向导。
- Windows 本地安装时，可执行文件通常位于 `.venv/Scripts/sentaurus-mcp.exe`；这不代表 Windows 已能运行你的 Sentaurus。

连接成功后，客户端应能发现下表中的 **6 个工具**。提交前确认后台执行器已经启动。

## 怎么向助手提问

完成配置并提供你已检查的输入脚本后，可以这样说：

> 用我提供的 SDevice 输入文件建立实验。先保存输入，告诉我实验编号，暂时不要提交。

> 提交刚才的实验。随后查询状态，告诉我当前阶段和已用时间。

> 读取这个实验新增的日志。把日志中的报错与可能原因分开说明，不要自动重跑。

> 列出这个实验生成的文件，告诉我哪些是日志、哪些是原生结果。

这些是**使用方式示例**，不是已经完成的仿真结果。助手需要拿到完整脚本；本工具不会自动补齐物理模型，也不会自动认定结果正确。

<details>
<summary>展开查看工具名称和用途</summary>

| 工具名称 | 用途 |
| --- | --- |
| `create_experiment` | 保存文本输入和阶段配置，不启动计算 |
| `submit_experiment` | 将已准备实验加入队列；重复提交不会重新启动同一实验 |
| `list_experiments` | 分页列出历史实验 |
| `get_experiment` | 查询状态、输入清单、进程编号及耗时 |
| `read_log` | 按字节位置读取一段日志 |
| `list_artifacts` | 列出结果文件，不把大型 TDR 文件塞进对话 |

输入格式：`files` 是“文件名 → 文本内容”的字典；`stages` 是阶段列表，每项包含 `tool` 和 `input_file`。工具名必须出现在配置的 `tools` 中，输入文件必须已提供。当前每个实验的文本输入合计上限为 2 MB。

能力说明也可通过资源 `sentaurus://capabilities` 读取。

</details>

## 运行原理

```mermaid
flowchart LR
    A["AI 助手"] --> B["MCP 接口"]
    B --> C["实验记录与队列"]
    C --> D["独立后台执行器"]
    D --> E["Sentaurus 仿真程序"]
    E --> F["原生结果与日志"]
    F --> B
```

MCP 是助手调用工具的统一接口；后台执行器负责实际运行。两者分开后，仿真不必一直占用一个对话请求。

实验按“项目 / 实验编号”保存。下面是目录示意，结果文件名由你的脚本决定：

```text
数据目录/
├── experiments.sqlite3       # 实验索引和运行状态
└── 项目名称/
    └── 实验编号/
        ├── 输入脚本
        ├── manifest.json     # 输入指纹和阶段配置
        ├── runner.log        # 执行器日志
        ├── stage-0.log       # 第一阶段日志
        ├── state.json        # 正常结束流程写出的最终状态
        └── 仿真产生的结果文件
```

同一项目可以保存多个实验，但当前目录**不是 Workbench 原生工程**。数据库中的运行状态可持续查询，输入和结果文件也独立保留。

## 常见问题

### 显示“完成”，就代表仿真正确吗？

不代表。`completed` 只表示各阶段程序正常退出。数值收敛、物理合理性和指标验收仍需检查，默认验证标签为“未审查”。

### 对话超时会停止仿真吗？

本工具没有固定的仿真运行时限。独立后台执行器正常工作时，MCP 客户端正常退出不会主动停止仿真。断线后先查询原实验，避免重复建立任务。

服务器关机、进程崩溃或外部调度器终止仍会影响任务；本版本尚不能自动恢复这些情况。

### 为什么提交不了？

先检查后台执行器是否在线、两个进程是否使用同一配置、是否启用了写入操作，以及输入文件是否在建立实验后被修改。修改过的输入会被指纹检查拒绝，应建立新的实验记录。

### 为什么一直显示运行中？

先查真实进程和日志。异常退出后状态可能没有及时写回，本版本尚未实现自动校正。不要直接清空运行状态来绕过并发限制。

### 可以直接读取 TDR 画图吗？

暂时只能列出文件。TDR 解析、原生切片图、曲线提取和打包导出还没有实现。

### 记录了哪些时间和资源？

记录阶段耗时、总运行耗时、进程编号、操作系统标识和主机可见 CPU 数量。**主机 CPU 数量不是本实验实际使用的核数**；进程内存峰值、完整硬件配置和优化到达目标的总耗时尚未完整采集。

### 可以给任意人使用吗？

输入脚本会以运行账号的权限执行，本工具不是脚本沙箱。应只连接可信客户端，并在操作系统或调度器中设置资源和账号权限。

## 开发与验证

安装测试依赖并运行：

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

已记录的本机验证：Windows、Python 3.12，**5 项测试通过**，覆盖真实 MCP 协议连接、客户端退出后后台任务继续、重复提交、输入校验和并发数量限制。

测试使用短小的 Python 模拟任务，**没有执行真实 Sentaurus 仿真**。已提供 Linux 自动测试配置，其运行状态以仓库“操作（Actions）”页面为准。详见[验证记录](VALIDATION.md)。

## 后续方向

以下是尚未完成的方向，不是当前可用功能：

- 接入真实 Sentaurus 环境，验证各版本的批处理参数。
- 原生 Workbench 工程创建与追加实验。
- CPU、内存和许可证准入检查。
- 任务取消、异常状态校正与恢复。
- TDR 解析、指标提取、原生图像和结果打包。

## 开发背景

本项目源于使用 Codex 辅助开展 Sentaurus TCAD 科研的实践。开发工作结合了通过 VNC Viewer 查看远程 Sentaurus 原生界面、脚本执行、日志分析和结果核对，并逐步将实验管理流程整理为可复用的 MCP 接口。

| 组成 | 在这套工作方式中的作用 |
| --- | --- |
| Codex | 辅助编写与修改脚本、整理实验流程、分析日志及开发工具 |
| VNC Viewer | 查看远程 Sentaurus 界面，辅助人工核对结构和运行情况 |
| Sentaurus | 执行实际的结构、网格及器件仿真 |
| 本项目 MCP 与独立后台执行器 | 为 AI 客户端提供实验准备、任务提交、状态查询和日志读取接口，并启动批处理任务 |

当前发布版本通过服务器上的独立后台执行器启动仿真，不依赖 Codex 操作 VNC Viewer；其他支持相应 MCP 连接方式的 AI 客户端也可接入。VNC 图形界面自动操作、SDE 自动交互建模和原生截图不属于当前发布版本的功能。

开发过程中使用的私人科研工作台、服务器配置和器件实验数据不随本仓库发布。上述背景说明不代表当前 MCP 已完成真实 Sentaurus 端到端验证；验证范围以[验证记录](VALIDATION.md)为准。

## 参考与许可

说明文档的组织参考了 [Playwright MCP](https://github.com/microsoft/playwright-mcp) 和 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 的用途介绍、快速开始与分层说明方式。

架构调研参考：[Ansys Mechanical MCP](https://github.com/ansys/pymechanical-mcp)、[Ansys AEDT MCP](https://github.com/ansys/pyaedt-mcp)、[OpenFOAM MCP](https://github.com/SciMate-AI/openfoam-mcp)。本项目独立实现，没有复制这些项目的源代码。

本项目使用官方 MCP Python SDK，版本约束为 `>=1.12,<2`。

本项目原创代码与文档采用 [Apache License 2.0](LICENSE)，版权声明：Copyright 2026 HanKin666。第三方依赖遵循各自的许可证。

本许可证不授予 Sentaurus 或其他第三方商业软件的使用权；使用者仍需自行取得相应授权。项目非 Synopsys 官方产品，不包含商业软件、手册或授权文件。
