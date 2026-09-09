# Ncatbot

基于 NcatBot、NapCat 和 OneBot 的 QQ 机器人插件集合。

## 运行准备

1. 准备 Python 3.10 或更高版本，并创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. 安装项目依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. 安装并登录 NapCat，确保 WebSocket 地址与 [config.yaml](config.yaml) 中的配置一致。
4. 配置 [config.yaml](config.yaml) 中的机器人账号、所有者 QQ 号和外部 API。
5. 启动开发模式：

```powershell
ncatbot dev
```

插件目录为 [plugins](plugins)，开启热重载后，修改插件文件会自动重新加载。

`requirements.txt` 只负责 Python 包。NapCat、QQ 登录状态和外部 API 密钥需要单独准备，不会通过 pip 自动安装。

## 配置说明

所有外部 API 地址集中在 [config.yaml](config.yaml) 的 `apis` 节点中，包括：

- Agnes AI：文本对话、图片生成和翻译。
- B 站、微博：用户资料和动态接口。
- GitHub：仓库和 Release 接口。
- wttr.in：天气查询。
- QuickChart：二维码生成。
- is.gd：短链接生成。
- UAPI：EPIC 免费游戏查询。

不要把真实的 `api_key`、WebUI Token、WebSocket Token 或 B 站 Cookie 提交到公开仓库。建议使用本地配置文件或环境变量，并轮换已经暴露过的密钥。

B 站 Cookie 配置示例：

```yaml
bilibili_monitor:
  cookie: "SESSDATA=...; bili_jct=...; DedeUserID=..."
```

## 帮助命令

`.help` 只显示功能类别：

```text
.help
```

查看某类功能的详细指令，可以使用名称或序号；两者之间的空格可有可无：

```text
.help 新闻资讯
.help新闻资讯
.help 5
.help5
```

`.帮助` 是 `.help` 的中文别名。

类别编号如下：

| 编号 | 类别 |
| --- | --- |
| 1 | AI功能 |
| 2 | 图片娱乐 |
| 3 | 游戏资讯 |
| 4 | 计算工具 |
| 5 | 新闻资讯 |
| 6 | 订阅监控 |
| 7 | 群管理 |
| 8 | 提醒任务 |
| 9 | 实用工具 |
| 10 | 权限与状态 |
| 11 | 下载工具 |

## 功能命令

### AI功能

```text
.ai <问题>
.ai出图 <描述>
```

群聊中直接 @机器人并发送内容，也可以触发 AI 对话。

### 图片娱乐

```text
.jk
.loli [数量] [标签]
.萝莉 [数量] [标签]
/r18 [数量] [标签]
/清理缓存
/loli_clear
```

`.jk` 获取随机图片。`.loli` 和 `.萝莉` 获取随机二次元图片，数量最多 10 张；如果省略标签，默认使用“萝莉”。
`/r18` 获取 R18 二次元图片，仅支持私聊，数量最多 5 张。`/清理缓存` 和 `/loli_clear` 清理 Lolicon 图片缓存。

### 下载工具

```text
.jm <本子ID>
.jmzip <本子ID>
```

`.jm` 下载并发送禁漫本子 PDF；`.jmzip` 下载并发送 ZIP，ZIP 发送失败时回退发送 PDF。两个命令都支持群聊和私聊，本子 ID 必须是纯数字。下载文件会缓存到项目根目录的 `pdf/` 文件夹。

### 游戏和新闻

```text
.每日新闻
.免费游戏
```

每日新闻按计划推送到机器人所在的群；EPIC 免费游戏在每周五的计划时间推送。手动命令支持群聊和私聊。

### 计算工具

```text
.calc <表达式>
.计算 <表达式>
```

### 订阅监控

```text
.b站订阅 <UP主UID>
.b站取消订阅 <UP主UID>
.b站列表

.微博订阅 <微博UID或链接>
.微博取消订阅 <微博UID或链接>
.微博列表

.订阅 rss <URL>
.订阅 github <owner/repo>
.订阅列表
.取消订阅 <编号>
```

B 站和微博会在保存前验证目标是否存在，并返回目标名称。RSS 和 GitHub 订阅也会先验证地址或仓库。

订阅列表按作用域隔离：

- 群聊订阅按群号隔离。
- 私聊订阅按用户 QQ 号隔离。
- 不同群组和不同用户不会共享 B 站、微博订阅。
- RSS/GitHub 订阅目前只支持群聊，并按群号隔离。

### 群管理

```text
.禁言 @用户或QQ号 [分钟]
.解禁 @用户或QQ号
.踢出 @用户或QQ号
.全员禁言
.解除全员禁言
.公告 <内容>
```

群管理命令需要群主或群管理员权限。`.公告` 当前发送的是一条格式化群消息，不是 NapCat 的正式群公告动作。

### 提醒任务

```text
.提醒 20分钟后 开会
.提醒列表
.取消提醒 <编号>
```

支持秒、分钟、小时和天。创建提醒支持群聊和私聊；群提醒触发时会 @创建者，私聊提醒直接发送给创建者。提醒列表和取消提醒目前只支持群聊。

### 实用工具

```text
.天气 <城市>
.翻译 <内容>
.翻译 日译中 <内容>
.二维码 <文字或链接>
.链接 <URL>
.短链接 <URL>
```

### 权限与状态

```text
.授权 @用户或QQ号
.取消授权 @用户或QQ号
.权限列表
.状态
.插件状态
.错误日志
```

授权管理需要群主或群管理员。`.权限列表` 展示已授权用户；`.状态` 和 `.插件状态` 不限制权限；`.错误日志` 仅 `config.yaml` 中 `root` 对应的机器人所有者可以查看。

## 插件和运行数据

每个插件目录包含一个 `manifest.toml` 和一个 `plugin.py`。运行时数据不建议提交到 Git，常见文件包括：

```text
plugins/feed_monitor_plugin/subscriptions.json
plugins/reminder_plugin/reminders.json
plugins/permission_plugin/permissions.json
plugins/*/state.json
```

日志位于 [logs](logs)，框架临时数据位于 [data](data)，NapCat 运行文件位于 [napcat](napcat)。这些目录应加入 `.gitignore`，不要作为项目源码提交。