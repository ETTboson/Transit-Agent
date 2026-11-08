<p align="center">
  <img src="assets/Mascot.png" alt="Transit-Agent 吉祥物" width="128">
</p>

<h1 align="center">Transit-Agent: 面向城市交通分析的自主规划智能体</h1>

<p align="center">
  <a href="README.md">English</a> · 简体中文
</p>

## Overview

![Transit-Agent 总览](assets/Overview.png)

Transit-Agent 将交通问题转化为可执行的分析任务。它识别问题中的对象、角色与任务类型，构建任务依赖图，结合专业工具与代码开展分析，并依据结果和执行反馈继续任务、调整计划或提交答案，保留相应的分析步骤与依据。

## Contributions

- 自主组织交通分析：围绕对象、角色和分析任务类型进行规划，通过任务依赖图组织计算与结果传递，支持根据反馈修订分析。
- 结合专业工具与代码：提供可组合的交通分析能力，支持样本比较、持续变化检测和空间分析，并允许模型编写代码完成具体任务。
- 构建任务集与评价方案：结合规划文件、车辆观测、小区画像与合成情境，设置分析计算、方案比较及更新任务，从答案、证据、修订、交付和资源开销等方面评价系统。

## Quickstart

使用 Python 3.11，在项目根目录创建虚拟环境：

```bash
python -m venv .venv
```

激活环境：Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`；Linux / macOS 使用 `source .venv/bin/activate`。

安装依赖，并检查示例资料：

```bash
python -m pip install -r requirements.txt
python -X utf8 -m agent.planning --data-dir benchmark/demo/data --question "检查资料是否具备开展站点调整分析的条件" --prepare-only
```

该示例使用虚构资料演示读取接口，检查过程不调用模型 API。

准备自己的资料后，可通过当前公交规划入口启动分析：

```bash
python -X utf8 -m agent.planning --data-dir data/my_case --question "分析站点调整对到站条件的影响，提交结果表和地图" --model deepseek-flash --temporary-key
```

程序会提示输入 API 密钥，并将结果页、分析代码及运行记录保存到 `data/planning_runs/`。

## 仓库结构

```text
agent/                  模型配置与智能体规划循环
  tools/                Transit-Agent 工具
benchmark/              评测框架
  questions/            评测题目
  references/           参考流程与答案
  demo/                 虚构资料接口示例
evaluate/              评测入口
tests/                 软件回归测试
```

`agent/models.py` 保存模型适配与凭据读取逻辑，`agent/runtime.py` 保存规划入口的模型请求设置与共用提示，`agent/planning.py` 定义动作与预算。

使用本地评分程序评测已有运行记录：

```bash
python -m evaluate.score --scorer /path/to/scorer.py --root /path/to/runs
```

评分程序提供 `score(root, output)` 函数，`root` 为运行目录，`output` 为新建的评分结果子目录，默认为 `scores`。评分程序的配套模块与参考资料沿用本地目录结构。
