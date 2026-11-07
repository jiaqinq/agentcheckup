# agentcheckup

> 在 agent 出错之前，先给它的环境做个体检。

[English](README.md) | 简体中文

**所有 MCP 工具都只看一个 server。没有一个回答「同时装五个会发生什么」。**

```console
$ agentcheckup

agentcheckup 0.4.0  |  3 server(s)  |  4 tool(s)  |  ~442 tokens per request

  Grade C    Score  79/100   1 error  2 warning  1 info

  CONFLICTS (1)
    AGT201  Tool name 'read_file' is exposed by both 'files' and 'git'.
            [files/read_file <-> git/read_file]
            fix: 硬冲突：客户端只保留一个，另一个永远调不到。改名，或用网关加前缀。

  RISKS (2)
    AGT101  Server 'github' runs unpinned npx package '@modelcontextprotocol/server-github'.
    AGT107  Server 'github' stores credential(s) inline: GITHUB_PERSONAL_ACCESS_TOKEN.

  NUDGES (1 across 1 rule(s), no score impact)
    AGT105  Server did not return a tool list  (1)
            github
```

## 没人在测的三个问题

两个 server 互相看不见，但你的模型看得见。它拿到的是五个 server 摊平后的
47 个工具，只能靠描述相似度选——它没有任何办法知道 `files.read_file` 和
`git.read_file` 是两回事。

**1. 硬冲突。** 两个 server 暴露同名工具，客户端只保留一个，另一个静默不可达。
你花一下午 debug「为什么读不到文件」，答案是「它调的是另一个」。

**2. 软冲突。** `github.search` 和 `docs.search` 描述重叠 70%。选择变成抛硬币，
表现和模型不稳定一模一样。但问题不在模型，在你的清单。

**3. 上下文税。** agent 在**每一次**请求里都为完整工具清单付费。47 个工具、
每个 200 字描述，用户还没开口就已经几千 token。没人做预算，因为没人测量。

`agentcheckup` 用一条命令把这三件事都量出来。

## 查什么

| 层 | 回答什么问题 | 规则 |
|---|---|---|
| **冲突** | 我的 agent 会不会选错工具？ | AGT201–AGT203 |
| **风险** | 我的配置安全吗？ | AGT001–AGT107 |
| **预算** | 每次请求要为清单付多少 token？ | 每次运行都报 |

共 36 条规则，完整说明见 [docs/rules.md](docs/rules.md)。

## 安装

```bash
pip install agentcheckup
```

需要 Python 3.10+。**零运行时依赖**——不依赖 SDK、不需要 tokenizer、不做 embedding、
不联网。

## 用法

### 一条命令，不带参数

```bash
agentcheckup
```

自动找到你的配置：Claude Desktop、Claude Code（含 per-project 的 `mcpServers`）、
Cursor、Windsurf、Cline，以及项目内的 `.mcp.json` / `.cursor/mcp.json` /
`.vscode/mcp.json`，逐个拉起 server、收集工具、出报告。

启动失败的 server 报 `AGT105` 后跳过，**不会中断整次体检**。一个坏 server 不该
挡住另外四个的审计。

### 常用参数

```bash
agentcheckup --no-spawn          # 只看配置，不启动进程
agentcheckup --config path.json  # 补一个没被发现的配置
agentcheckup --no-discover       # 只审计 --config 传入的
agentcheckup --format json       # 给程序读
agentcheckup --fail-on warning   # CI 门禁
```

### 单个 server

```bash
agentcheckup scan tools.json                    # 各种 JSON 形状都吃
agentcheckup scan --cmd "python my_server.py"   # 实机握手
agentcheckup config ~/.claude.json              # 只跑配置规则
agentcheckup rules                              # 列出全部规则
```

### 接入 CI

```yaml
- name: Diagnose agent setup
  run: |
    pip install agentcheckup
    agentcheckup --no-spawn --fail-on warning
```

退出码：`0` 干净，`1` 有达到阈值的发现，`2` 用法/加载错误。

## 冲突是怎么判的

不用 embedding、不用模型、不联网——因为一个需要 200MB wheel 的 linter，就是一个
在飞机上跑不起来的 linter。

每一对跨 server 的工具按两个信号打分：

- **名字重叠**：归一化后的 token Jaccard（`read_files` ≡ `read_file`）
- **描述重叠**：去停用词、粗词干化之后的 token Jaccard

判定条件：描述重叠 ≥ 65% **且** 名字共享中心词，或加权分 ≥ 0.55。
共享中心词这个约束是关键——没有它，`search_repositories` 和 `search_documents`
会因为都含 "search" 被误报，而**充满噪音的报告比没有报告更糟**。

这是启发式，文档里写明了。`AGT203` 是警告，不是判决。

## 分数是怎么算的

大多数 linter 在这里翻车：一条在 18 个工具上全部触发的规则，是**偏好**不是缺陷，
每条扣 1 分就会把官方 MCP server 打成 0/100——那个数字毫无意义。所以评分是**校准出来的**，不是拍脑袋定的：

| 级别 | 扣分 | 含义 |
|---|---|---|
| `error` | 10 | 会坏，或者会出事 |
| `warning` | 3 | 大概率导致行为错误 |
| `info` | 1，**总数上限 10** | 人来判断 |

预算是**每个工具 20 分**，所以 200 个工具的清单不会因为大而被扣光，4 个工具的清单也不会因为小而被放过。

四个真实输入的校准结果：

| 输入 | 工具数 | 结果 |
|---|---|---|
| 干净样本 | 2 | A · 100 |
| 官方 `fetch` + `git` + `time` | 18 | B · 87 |
| 硬冲突 + 未锁版本 + 明文密钥 | 4 | C · 79 |
| 故意写坏的样本 | 7 | F · 36 |

重复发现会合并：12 个工具都缺参数描述，只打一行并列出这 12 个；info 级发现按规则汇总。
**读不完的报告等于没人看的报告。**

## 设计原则

- **零运行时依赖。** 因为传递依赖挂掉而失效的诊断工具，比没有更糟。
- **规则编号永久不变。** `AGT201` 的含义永远不变。
- **每条发现都带修法。** 只说「这不好」的规则，训练用户忽略输出。
- **降级而不是崩溃。** 起不来的 server 是一条发现，不是中断。
- **永不联网。** 你的配置不会离开本机。这是商业扫描器结构上给不了的承诺。
- **启发式要标明是启发式。** `info` 的意思是「人来判断」。分数是讨论起点，不是认证。

## 这不是什么

- 不是沙箱。它告诉你清单有风险，但拦不住 server。
- 不是运行时防护。它不在 agent 会话里运行。
- 不是 MCP 协议校验器。协议一致性由官方 `modelcontextprotocol/conformance` 负责。

## 贡献

加一条规则大约十分钟、一个文件，见 [CONTRIBUTING.md](CONTRIBUTING.md)。
规则和客户端适配器是这个项目的全部意义，这类 PR 最受欢迎。

## 许可

MIT
