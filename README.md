# TGbot - 京东Cookie和IP白名单管理机器人

## 功能介绍

TGbot是一个功能强大的Telegram机器人，主要用于管理京东Cookie（CK）和IP白名单。它可以帮助您实现以下功能：

1. **京东Cookie管理**
   - 自动从主青龙面板获取CK并保存到文件
   - 将CK同步到多个青龙面板，保留原始备注
   - 支持按pt_pin筛选CK，可设置保留或排除特定CK
   - 支持将不同的CK保存到不同的文件中

2. **IP白名单管理**
   - 自动检测IP变动并更新白名单
   - 支持手动添加、删除和查询白名单

3. **青龙面板交互**
   - 支持配置多个青龙面板
   - 查询CK状态和管理面板CK
   - 支持为每个面板单独设置CK同步规则

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

3. **CK同步和保留配置**
   - `PRESERVED_PT_PINS`: CK同步配置，可为每个面板单独设置保留规则
     ```json
     {
       "default": {                 // 默认配置，当面板名称未单独配置时使用
         "pins": ["pin1", "pin2"], // pt_pin列表
         "mode": "exclude"         // exclude表示不同步列表中的CK，include表示只同步列表中的CK
       },
       "panel_name_1": {           // 特定面板的配置
         "pins": ["special_pin"],
         "mode": "include"
       }
     }
     ```

   - `CK_FILE_PATH`: CK文件路径配置，可为每个文件设置筛选规则
     ```json
     {
       "default": {                 // 默认配置
         "path": "path/to/ck.txt", // 文件路径
         "pins": ["pin1", "pin2"], // pt_pin列表
         "mode": "exclude"         // exclude表示不保存列表中的CK，include表示只保存列表中的CK
       },
       "backup": {                 // 备份文件配置
         "path": "path/to/backup.txt",
         "pins": ["special_pin"],
         "mode": "include"
       }
     }
     ```

4. **Redis数据库配置**
   - `REDIS_HOST`: Redis服务器地址
   - `REDIS_PORT`: Redis服务器端口
   - `REDIS_DB`: Redis数据库编号
   - `REDIS_PASSWORD`: Redis数据库密码

5. **代理API配置**
   - `PROXY_AUTH_KEY`: 代理API认证密钥
   - `PROXY_API_URL`: 代理API地址，用于获取和更新IP白名单

6. **其他配置**
   - `CURRENT_IP_KEY`: Redis中存储当前IP的键名
   - `CURRENT_CK_HASH_KEY`: Redis中存储当前CK哈希值的键名
   - `LOG_DIR`: 日志文件目录

7. **定时任务配置**
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

### CK同步和保留功能

程序提供了灵活的CK同步和保留功能：

1. **面板间CK同步**
   - 可以通过`PRESERVED_PT_PINS`配置为每个面板设置不同的同步规则
   - 支持include模式（只同步列表中的CK）和exclude模式（不同步列表中的CK）
   - 默认配置适用于未单独配置的面板

2. **多文件CK保存**
   - 可以通过`CK_FILE_PATH`配置将不同的CK保存到不同的文件中
   - 每个文件可以设置自己的筛选规则
   - 支持include模式（只保存列表中的CK）和exclude模式（不保存列表中的CK）

## 注意事项

1. 请确保Redis服务器已正确配置并运行
2. 青龙面板需要配置正确的Client ID和Client Secret
3. 程序会自动创建必要的目录和文件
4. 定时任务会在后台自动运行，无需手动触发
5. 敏感信息（如API密钥、令牌等）应妥善保管，不要泄露

## 常见问题

### 无法连接到Telegram API

如果您所在的网络环境无法直接访问Telegram API，请配置`TELEGRAM_PROXY_API`使用代理服务。

### CK同步失败

请检查各青龙面板的配置是否正确，特别是URL、Client ID和Client Secret。同时，确认`PRESERVED_PT_PINS`配置是否正确设置。

### Redis连接错误

确保Redis服务器已启动，并且配置的主机、端口和密码正确。

### CK文件保存问题

如果CK未正确保存到文件，请检查`CK_FILE_PATH`配置是否正确，以及文件路径是否存在或可写入。