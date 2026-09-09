# Sentaurus MCP｜让 AI 助手调用 TCAD 仿真 

**中文** | [English](README.en.md)

**把准备输入、提交仿真、查看状态和读取日志，接入支持 MCP 的 AI 助手。**

面向已经使用 Sentaurus 的半导体器件研究者。你可以让助手建立实验、提交已有脚本、查询运行进度，而不用在对话与终端之间反复复制信息。

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

连接成功后，客户端应能发现下表中的 **8 个工具**。提交前确认后台执行器已经启动。

## 首次使用：连接诊断与引导

### 弹窗或终端问答配置

在自己的电脑上更新安装后运行（将输出路径改到本机合适的数据盘）：

```bash
python -m pip install -e '.[setup]'
python -m sentaurus_mcp.setup --gui --output connection-local.txt
```

去掉 `--gui` 则在终端逐项询问。弹窗需要 Python 的 Tk 支持；没有桌面或 Tk 时使用终端模式。`--load connection-local.txt --output connection-new.txt` 可读取指定的旧配置作为默认值，绝不自动扫描其他程序的配置和密码。

向导询问：VNC／SSH／不确定、主机地址、实际 TCP 端口、用户名（VNC 可留空）、认证方式；SSH 还询问服务器 Python 和 MCP 配置路径，未知可先留空。`主机:1` 可能是 VNC 显示编号，不自动猜为 TCP 端口。选择“不确定”时，仍需要提供端口；可授权读取该端口握手来识别 SSH 或 VNC，不扫描其他端口，不尝试登录。

配置保存为 UTF-8 `.txt`（内部为 JSON），包含非密码连接信息、状态以及条件满足时生成的只读 MCP 配置；已有文件不覆盖。密码在本地隐藏输入，可选保存到系统凭据库，文本只存凭据引用。安全凭据库不可用时不会退回明文保存；配置仍含服务器地址等信息，请只保存在自己的电脑上。

**当前向导不自动使用保存的密码登录，也不安装服务器代理。** VNC 只有端口和密码时可保存配置，但还需要确认服务器地址；要接入当前 MCP，需另有 SSH 通道或在服务器本机运行客户端。SSH 后台认证仍需用户配置密钥／认证代理等方案。已有软件“登录成功”与向导“配置已保存”是不同状态。

已在本地测试参数校验、单端口握手、文本配置保存与读取，以及 VNC 终端问答流程；图形弹窗和各平台真实凭据库仍需用户环境验证。切勿把密码发给助手或填入 MCP 工具调用参数。

更新安装后，可让助手调用 `diagnose_environment`。即使没有配置，也会返回当前主机的环境、配置、存储权限、执行器心跳和程序路径状态；不创建实验目录，不启动仿真，也不验证许可证。

只有 VNC 时，调用 `get_connection_guide(mode="vnc")` 获取限制说明。有 SSH 时，提供主机、用户名、端口、服务器 Python 和配置路径，生成只读客户端配置。该工具不连接、不自动安装，也不接收密码。

本机终端示例（替换占位内容）：

```bash
python -m sentaurus_mcp.doctor
python -m sentaurus_mcp.doctor --mode vnc
python -m sentaurus_mcp.doctor --mode ssh --host server.example.com --user your_user --port 22 --remote-python /absolute/path/.venv/bin/python --remote-config /absolute/path/config.json
```

最后一条默认仅生成配置；加 `--probe` 才通过 SSH 执行远程只读诊断。服务器须先安装包含诊断模块的版本。连接检查最多等待 30 秒，不会停止仿真，也不会部署或启动执行器。请先自行准备认证、核对主机密钥。当前向导支持域名和 IPv4，暂不支持 IPv6。

收到远程诊断也不等于许可证有效；未收到时明确标为失败或未检查。部署仍按下文手动完成；本地配置弹窗不是远程登录或自动部署功能。

## 远程服务器连接

**本机运行 MCP 不需要服务器登录信息；从自己的电脑连接远程服务器时，需要先配置 SSH。** 本地连接向导见上文；没有接收密码的 MCP 工具。

### 需要准备哪些信息

| 信息 | 从哪里获取、填在哪里 |
| --- | --- |
| 服务器地址 | 向管理员获取 IP 或域名，替换示例中的 `server.example.com` |
| SSH 端口 | 向管理员确认，替换示例中的 `22`；不要照填 VNC 端口 |
| Linux 用户名 | 替换 `your_user`，该账号需有实验目录写入权和软件执行权限 |
| 登录认证 | 交互登录可用密码；后台连接建议使用管理员允许的 SSH 密钥或其他非交互认证 |
| MCP 与配置文件路径 | 填服务器上的绝对路径，必须与独立后台执行器使用的配置一致 |
| Sentaurus 运行环境 | 在服务器配置软件、许可证及必要环境变量 |

**SSH 用于执行程序，VNC 用于查看远程桌面。** VNC 的显示编号、端口和密码不能当作 SSH 配置；能够打开 VNC 不代表已具备 SSH 登录或仿真权限。

### 先由你在本地终端测试登录

以下主机名和用户名均为占位内容：

```bash
ssh -p 22 your_user@server.example.com
```

首次连接时，向管理员核对服务器主机密钥指纹，再确认保存。若使用密码，由你在 SSH 提示中输入；终端不显示密码字符是正常现象。不要把密码或私钥内容放进 README、客户端配置、命令参数或发给 LLM。

**一次密码登录成功，不代表 MCP 后台连接可以自动登录。** 多数客户端后台启动 SSH 时没有交互终端。下面的配置明确启用非交互模式，未准备好认证时会直接失败，不会弹出密码框。密钥有口令时，可由你通过本机 SSH 认证代理加载；也可由管理员配置组织允许的认证方案。若只允许逐次输入密码，需要客户端提供安全交互认证能力，当前项目没有实现这一功能。

### 配置客户端通过 SSH 启动服务器上的 MCP

先按前文在服务器安装 MCP、配置 Sentaurus，并独立启动后台执行器。然后在本机客户端中填写：

```json
{
  "mcpServers": {
    "sentaurus": {
      "command": "ssh",
      "args": [
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-p",
        "22",
        "your_user@server.example.com",
        "env",
        "SENTAURUS_MCP_CONFIG=/absolute/path/to/sentaurus-mcp/config.json",
        "SENTAURUS_ENABLE_ACTIONS=0",
        "/absolute/path/to/sentaurus-mcp/.venv/bin/sentaurus-mcp"
      ]
    }
  }
}
```

这里的 `ssh` 是**本机**的 OpenSSH 客户端；如果不在搜索路径中，改为实际可执行文件路径。后面的 MCP 和配置文件路径都是**服务器端**路径。示例路径不含空格；远程路径含空格时需正确处理远端 shell 引号，不能直接照搬。

- `-T` 不分配伪终端，让 MCP 使用标准输入输出通信。
- `BatchMode=yes` 禁止交互认证提示；请提前准备认证。
- `StrictHostKeyChecking=yes` 要求主机密钥已核验并保存。
- 默认 `SENTAURUS_ENABLE_ACTIONS=0`，先只读检查；需要建立、提交实验时改为 `1`。
- 需要指定密钥时，可在主机名前添加 `"-i", "/absolute/local/path/to/private_key"`，或使用本机 SSH 配置。这里只填写文件路径，不填写密钥内容。
- 非交互连接未必加载交互登录的环境配置。服务器后台执行器必须具备 Sentaurus 的许可证和运行库环境；MCP 的标准输出也不能混入登录脚本的提示文字。

连接后先让助手列出实验，再测试授权范围内的提交。发现 6 个 MCP 工具只证明接口可连接，**不证明 Sentaurus 已运行或仿真已通过验证**。

常见错误：`Permission denied` 通常指认证问题；连接拒绝或超时需检查地址、SSH 端口和网络；主机密钥不匹配需向管理员核实，不能直接关闭检查；“执行器不在线”需检查后台进程和配置路径。

这些是连接配置说明，尚未作为本项目的远程端到端测试结果。参数依据：[OpenSSH 命令说明](https://man.openbsd.org/ssh.1)、[SSH 配置说明](https://man.openbsd.org/ssh_config.5)。

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
