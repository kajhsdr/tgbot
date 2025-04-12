# TGbot - 京东Cookie和IP白名单管理机器人

## 功能介绍

TGbot是一个功能强大的Telegram机器人，主要用于管理京东Cookie（CK）和IP白名单。它可以帮助您实现以下功能：

1. **京东Cookie管理**
   - 自动从主青龙面板获取CK并保存到文件
   - 将CK同步到多个青龙面板，保留原始备注
   - 支持保留指定的CK（通过pt_pin设置）

2. **IP白名单管理**
   - 自动检测IP变动并更新白名单
   - 支持手动添加、删除和查询白名单

3. **青龙面板交互**
   - 支持配置多个青龙面板
   - 查询CK状态和管理面板CK

4. **系统管理功能**
   - 查看系统运行状态
   - 清理日志文件

## 安装依赖

### 所需依赖

程序依赖以下Python库：

- aiofiles
- httpx
- psutil
- pytz
- redis-py (异步版本)
- python-telegram-bot

### 快速安装依赖

```bash
# 使用pip安装所有依赖
pip install aiofiles httpx psutil pytz redis python-telegram-bot

# 或者使用requirements.txt安装（如果有）
pip install -r requirements.txt
```

## 配置说明

### 关于配置文件

本项目使用`tgbot.json`作为配置文件。配置文件采用了结构化格式，每个配置项都包含`value`和`description`字段，使得配置文件本身就包含了各配置项的用途说明。

### 如何使用示例配置文件

`tgbot.json.example`文件包含了所有配置项的详细说明。您可以参考这个文件来了解各配置项的用途，但请注意：

- 实际使用时，请使用`tgbot.json`文件
- 如需修改配置，请编辑`tgbot.json`文件，而不是示例文件
- 示例文件中的注释仅供参考，不应被复制到实际配置中

### 配置项说明

配置文件主要包含以下几类设置：

1. **Telegram相关配置**
   - `TELEGRAM_TOKEN`: Telegram机器人的API令牌
   - `TG_USER_IDS`: 允许使用此机器人的Telegram用户ID列表
   - `TELEGRAM_PROXY_API`: Telegram API代理地址（在无法直接访问Telegram API的环境中使用）

2. **青龙面板配置**
   - `QL_URL`: 主青龙面板的URL地址
   - `CLIENT_ID`: 主青龙面板的Client ID
   - `CLIENT_SECRET`: 主青龙面板的Client Secret
   - `QL_PANELS`: 其他青龙面板配置列表，用于CK同步

3. **Redis数据库配置**
   - `REDIS_HOST`: Redis服务器地址
   - `REDIS_PORT`: Redis服务器端口
   - `REDIS_DB`: Redis数据库编号
   - `REDIS_PASSWORD`: Redis数据库密码

4. **代理API配置**
   - `PROXY_AUTH_KEY`: 代理API认证密钥
   - `PROXY_API_URL`: 代理API地址，用于获取和更新IP白名单

5. **文件路径配置**
   - `CK_FILE_PATH`: CK文件路径，用于存储和读取CK
   - `LOG_DIR`: 日志文件目录

6. **定时任务配置**
   - `CK_UPDATE_INTERVAL`: CK更新间隔（分钟）
   - `IP_UPDATE_INTERVAL`: IP白名单更新间隔（分钟）
   - `CK_SYNC_INTERVAL`: CK同步到其他面板的间隔（分钟）

## 使用方法

### 启动程序

```bash
python tgbot.py
```

### Telegram机器人命令

机器人支持以下命令：

- `/start` - 显示欢迎信息和帮助
- `/getck` - 获取当前CK文件内容
- `/ckstatus` - 查看CK状态
- `/ip` - 管理IP白名单
- `/cleanlogs` - 清理日志文件
- `/zt` - 获取系统状态信息
- `/ql` - 管理青龙面板CK
- `/syncck` - 手动执行CK同步

### IP白名单管理

使用`/ip`命令可以管理IP白名单，支持以下操作：

- `/ip add <IP>` - 添加IP到白名单
- `/ip del <IP>` - 从白名单删除IP
- `/ip list` - 查看当前白名单
- `/ip update` - 更新当前IP到白名单

### 青龙面板CK管理

使用`/ql`命令可以管理青龙面板CK，支持以下操作：

- `/ql list` - 列出所有CK
- `/ql enable <序号>` - 启用指定CK
- `/ql disable <序号>` - 禁用指定CK
- `/ql delete <序号>` - 删除指定CK

## 注意事项

1. 请确保Redis服务器已正确配置并运行
2. 青龙面板需要配置正确的Client ID和Client Secret
3. 程序会自动创建必要的目录和文件
4. 定时任务会在后台自动运行，无需手动触发

## 常见问题

### 无法连接到Telegram API

如果您所在的网络环境无法直接访问Telegram API，请配置`TELEGRAM_PROXY_API`使用代理服务。

### CK同步失败

请检查各青龙面板的配置是否正确，特别是URL、Client ID和Client Secret。

### Redis连接错误

确保Redis服务器已启动，并且配置的主机、端口和密码正确。