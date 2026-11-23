# RouteLab

通过编写 Python `solve(ctx)` 学习寻路、动态路由、运营商互联与网络安全防御的桌面教学游戏。

本项目由 **OpenAI Codex 实现并持续迭代开发**，根据项目发起者提供的需求与反馈完成代码、界面、教学事件和测试。

## 启动

安装 Python 3.10+，包含 Tcl/Tk。项目仅使用标准库，无需安装 pip 依赖。

Windows 下载并解压整个项目后，双击 **启动RouteLab.bat**，或在项目目录运行：

```console
py -3 RouteLab.py
```

其他带 Tk 图形环境的平台可运行 `python3 RouteLab.py`。

## 玩法

- 分步编写寻路算法，观察数据包逐跳传输。
- 根据延迟、故障和路由通告改进距离向量算法。
- 按运营商互联协议、费用与服务目标选择合规路线。
- 完成运营商任务后进入 S1、S2 安全教学，编写限速策略并检查可用性与误封。
- 动画完成后自动推进事件，保留玩家代码。支持固定种子、暂停、单步和时间线回看。
- <img width="2546" height="1498" alt="image" src="https://github.com/user-attachments/assets/99a0bdb0-3075-4fe4-929f-431a9e0181e2" />


## 执行模式

默认模式运行可信的本地 Python。子进程超时及协议长度限制无法隔离本机文件、网络或系统命令，因此只运行自己信任的代码。可选隔离后端尚未部署，显式选择时会拒绝执行。

## 测试与文档

```console
py -3 -m unittest discover -s tests -v
```

图形测试需要可用的 Tk 桌面环境。详细说明见 [使用指南](README_先看我.txt)、[接口说明](docs/API.md) 和 [验收记录](DELIVERY_REPORT.md)。
