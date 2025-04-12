#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CK和IP白名单管理机器人 - 优化版"""

# 优化内容：
# 1. 重构HTTP请求处理逻辑，提高代码复用性
# 2. 优化异常处理机制，增加更详细的错误日志
# 3. 改进sync_ck_to_panels函数，使其更高效且保留原始备注
# 4. 添加手动执行CK同步的命令功能
# 5. 优化配置结构，使其更易于维护和扩展

import asyncio
import hashlib
import json
import logging
import os
import shutil
import platform
from datetime import datetime, timedelta

import aiofiles
import httpx
import psutil
import pytz
from redis.asyncio import StrictRedis
from telegram import Update
from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# ================ 配置信息 ================
# 从JSON文件加载配置
def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tgbot.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # 提取配置值（新格式包含value和description字段）
        config = {}
        for key, item in config_data['config'].items():
            config[key] = item['value']
            
        print(f"✅ 已从 {config_path} 加载配置")
        return config
    except Exception as e:
        print(f"❌ 加载配置文件失败: {e}，将使用默认配置")
        # 默认配置，仅在无法加载配置文件时使用
        return {
            # Telegram Bot 配置
            'TELEGRAM_TOKEN': '',
            'TG_USER_IDS': [],
            'TELEGRAM_PROXY_API': '',
            
            # 主青龙面板配置
            'QL_URL': "",
            'CLIENT_ID': '',
            'CLIENT_SECRET': '',
            
            # 新增的青龙面板配置列表
            'QL_PANELS': [],
            
            # 需要保留的pt_pin列表
            'PRESERVED_PT_PINS': [],
            
            # Redis 数据库配置
            'REDIS_HOST': 'localhost', 
            'REDIS_PORT': 6379,
            'REDIS_DB': 0, 
            'REDIS_PASSWORD': '',
            
            # 代理白名单 API 配置
            'PROXY_AUTH_KEY': "",
            'PROXY_API_URL': "",
            
            # 文件和存储配置
            'CK_FILE_PATH': "scripts/beta/env/ck.txt",
            'CURRENT_IP_KEY': "current_ip",
            'CURRENT_CK_HASH_KEY': "current_ck_hash",
            'LOG_DIR': "logs/scripts",
            
            # 定时任务配置
            'CK_UPDATE_INTERVAL': 20,  # 分钟
            'IP_UPDATE_INTERVAL': 5,   # 分钟
            'CK_SYNC_INTERVAL': 30,    # 分钟
        }

# 加载配置
CONFIG = load_config()

# 时区设置
LOCAL_TIMEZONE = pytz.timezone('Asia/Shanghai')

# ================ 日志设置 ================
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[94m', 'INFO': '\033[92m', 'WARNING': '\033[93m',
        'ERROR': '\033[91m', 'CRITICAL': '\033[1;91m', 'RESET': '\033[0m'
    }
    
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, LOCAL_TIMEZONE).strftime(datefmt or '%m-%d %H:%M:%S')
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        log_format = f"{log_color}[%(asctime)s] {record.levelname[0]} | %(message)s{self.COLORS['RESET']}"
        formatter = logging.Formatter(log_format)
        formatter.formatTime = self.formatTime
        return formatter.format(record)

# 初始化日志
logger = logging.getLogger(__name__)

# Redis客户端将在main函数中初始化

# ================ 工具函数 ================
async def setup_logging():
    """设置日志记录器"""
    console = logging.StreamHandler()
    console.setFormatter(ColoredFormatter())
    
    for log_name in [__name__, "telegram", "httpx"]:
        log = logging.getLogger(log_name)
        log.setLevel(logging.INFO if log_name != "httpx" else logging.WARNING)
        log.handlers = []
        log.addHandler(console)
        log.propagate = False

async def safe_request(method, url, **kwargs):
    """安全的HTTP请求包装器，支持重试和错误处理"""
    timeout = kwargs.pop('timeout', 10.0)
    retries = kwargs.pop('retries', 2)
    error_detail = kwargs.pop('error_detail', '')
    
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await getattr(client, method)(url, **kwargs)
                response.raise_for_status()
                return response.json() if 'json' in response.headers.get('content-type', '') else response.text
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP错误 {e.response.status_code}: {url}"
            if attempt < retries - 1:
                logger.warning(f"⚠️ {error_msg}，正在重试 ({attempt+1}/{retries})")
                await asyncio.sleep(1)
            else:
                logger.error(f"❌ {error_msg} {error_detail}")
                raise
        except httpx.RequestError as e:
            error_msg = f"请求错误: {e} {url}"
            if attempt < retries - 1:
                logger.warning(f"⚠️ {error_msg}，正在重试 ({attempt+1}/{retries})")
                await asyncio.sleep(1)
            else:
                logger.error(f"❌ {error_msg} {error_detail}")
                raise
        except Exception as e:
            error_msg = f"未知错误: {e} {url}"
            if attempt < retries - 1:
                logger.warning(f"⚠️ {error_msg}，正在重试 ({attempt+1}/{retries})")
                await asyncio.sleep(1)
            else:
                logger.error(f"❌ {error_msg} {error_detail}")
                raise
    
    return None

async def notify(title, message, document=None):
    """发送通知给管理员"""
    base_url = CONFIG['TELEGRAM_PROXY_API'].rstrip('/')
    
    for user_id in CONFIG['TG_USER_IDS']:
        try:
            if document:
                with open(document, 'rb') as f:
                    files = {'document': f}
                    data = {'chat_id': user_id, 'caption': f"{title}\n\n{message}"}
                    await safe_request('post', f"{base_url}/bot{CONFIG['TELEGRAM_TOKEN']}/sendDocument", data=data, files=files)
            else:
                params = {'chat_id': user_id, 'text': f"*{title}*\n\n{message}", 'parse_mode': 'Markdown'}
                await safe_request('get', f"{base_url}/bot{CONFIG['TELEGRAM_TOKEN']}/sendMessage", params=params)
            return True
        except Exception as e:
            logger.error(f"❌ 发送通知给 {user_id} 失败: {e}")
    return False

# ================ 青龙面板操作 ================
class QingLongAPI:
    """青龙面板API操作封装类"""
    
    def __init__(self, url, client_id, client_secret, name="主面板"):
        self.url = url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.name = name
        self.token = None
    
    async def get_token(self):
        """获取青龙面板的访问令牌"""
        if self.token:
            return self.token
            
        try:
            result = await safe_request(
                'get', 
                f"{self.url}/open/auth/token", 
                params={'client_id': self.client_id, 'client_secret': self.client_secret},
                error_detail=f"面板: {self.name}"
            )
            self.token = result.get('data', {}).get('token')
            return self.token
        except Exception as e:
            logger.error(f"❌ 获取令牌失败 ({self.name}): {e}")
            return None
    
    async def _request(self, method, endpoint, **kwargs):
        """发送API请求的通用方法"""
        token = await self.get_token()
        if not token:
            raise ValueError(f"无法获取{self.name}的访问令牌")
            
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {token}'
        
        return await safe_request(
            method, 
            f"{self.url}{endpoint}", 
            headers=headers, 
            error_detail=f"面板: {self.name}",
            **kwargs
        )
    
    async def get_enabled_cookies(self):
        """获取青龙面板中启用的 Cookies"""
        try:
            result = await self._request('get', '/open/envs')
            
            cookies = []
            for item in result.get("data", []):
                if item.get('status') == 0 and item.get('name') == 'JD_COOKIE':
                    value = item.get('value', '')
                    parts = value.split(';')
                    pt_key = next((part for part in parts if "pt_key=" in part), "")
                    pt_pin = next((part for part in parts if "pt_pin=" in part), "")
                    if pt_key and pt_pin:
                        cookies.append(f"{pt_key.strip()};{pt_pin.strip()};")
            
            return cookies
        except Exception as e:
            logger.error(f"❌ 获取环境变量失败 ({self.name}): {e}")
            return []
    
    async def get_enabled_cookies_with_remarks(self):
        """获取青龙面板中启用的 Cookies 及其备注"""
        try:
            result = await self._request('get', '/open/envs')
            
            cookies_info = []
            for item in result.get("data", []):
                if item.get('status') == 0 and item.get('name') == 'JD_COOKIE':
                    value = item.get('value', '')
                    parts = value.split(';')
                    pt_key = next((part for part in parts if "pt_key=" in part), "")
                    pt_pin = next((part for part in parts if "pt_pin=" in part), "")
                    if pt_key and pt_pin:
                        cookies_info.append({
                            'value': f"{pt_key.strip()};{pt_pin.strip()};",
                            'remarks': item.get('remarks', '')
                        })
            
            return cookies_info
        except Exception as e:
            logger.error(f"❌ 获取环境变量及备注失败 ({self.name}): {e}")
            return []
    
    async def get_all_cookies(self):
        """获取青龙面板中所有的 Cookies（包括禁用的）以及它们的ID和状态"""
        try:
            result = await self._request('get', '/open/envs')
            
            cookies_info = []
            for item in result.get("data", []):
                if item.get('name') == 'JD_COOKIE':
                    value = item.get('value', '')
                    parts = value.split(';')
                    pt_key = next((part for part in parts if "pt_key=" in part), "")
                    pt_pin = next((part.strip() for part in parts if "pt_pin=" in part), "")
                    
                    if pt_key and pt_pin:
                        cookies_info.append({
                            'id': item.get('_id') or item.get('id'),
                            'value': value,
                            'pt_pin': pt_pin,
                            'status': item.get('status', 1)  # 0为启用，1为禁用
                        })
            
            return cookies_info
        except Exception as e:
            logger.error(f"❌ 获取所有环境变量失败 ({self.name}): {e}")
            return []
    
    async def delete_cookies(self, cookie_ids):
        """删除指定ID的Cookies"""
        try:
            if not cookie_ids:
                return True, "没有需要删除的Cookie"
            
            # 构造请求头
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # 使用DELETE方法发送请求
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(
                    method="DELETE",
                    url=f"{self.url}/open/envs",
                    headers={
                        'Authorization': f'Bearer {self.token}',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    data=json.dumps(cookie_ids)
                )
                response.raise_for_status()
                result = response.json()
            
            if result.get('code') == 200:
                return True, f"成功删除 {len(cookie_ids)} 个Cookie"
            else:
                return False, f"删除失败: {result.get('message', '未知错误')}"
        except Exception as e:
            logger.error(f"❌ 删除Cookie失败 ({self.name}): {e}")
            return False, f"删除出错: {str(e)}"
    
    async def add_cookies(self, cookies_info):
        """添加Cookies到面板"""
        try:
            if not cookies_info:
                return True, "没有需要添加的Cookie"
                
            # 准备环境变量数据
            envs = []
            for cookie_info in cookies_info:
                envs.append({
                    "name": "JD_COOKIE",
                    "value": cookie_info['value'],
                    "remarks": cookie_info.get('remarks', "")
                })
                
            # 发送请求
            result = await self._request('post', '/open/envs', json=envs)
            
            if result and result.get('code') == 200:
                return True, f"成功添加 {len(envs)} 个Cookie"
            else:
                return False, f"添加失败: {result.get('message', '未知错误')}"
        except Exception as e:
            logger.error(f"❌ 添加Cookie失败 ({self.name}): {e}")
            return False, f"添加出错: {str(e)}"

async def save_cookies_to_file(cookies):
    """保存 Cookies 到文件"""
    try:
        os.makedirs(os.path.dirname(CONFIG['CK_FILE_PATH']), exist_ok=True)
        async with aiofiles.open(CONFIG['CK_FILE_PATH'], 'w') as f:
            await f.write("\n".join(cookies))
        logger.info(f"✅ 已保存 {len(cookies)} 条 CK")
        return True
    except Exception as e:
        logger.error(f"❌ 保存 CK 失败: {e}")
        return False

def extract_pt_pin(cookie_str):
    """从cookie字符串中提取pt_pin值"""
    parts = cookie_str.split(';')
    for part in parts:
        if "pt_pin=" in part:
            return part.strip().replace("pt_pin=", "")
    return None

def should_preserve_cookie(pt_pin):
    """判断是否应该保留这个cookie（基于pt_pin）"""
    if not pt_pin:
        return False
        
    for preserved in CONFIG['PRESERVED_PT_PINS']:
        preserved_clean = preserved.replace("pt_pin=", "").strip(';')
        if preserved_clean == pt_pin:
            return True
    return False

# ================ IP 白名单操作 ================
async def get_current_ip():
    """获取当前 IP 地址"""
    try:
        return await safe_request('get', "https://4.ipw.cn/")
    except Exception as e:
        logger.error(f"❌ 获取当前 IP 失败: {e}")
        return None

async def manage_whitelist(operation, ip=None):
    """管理 IP 白名单"""
    service_map = {'add': 'AddWhite', 'del': 'DelWhite', 'list': 'GetWhite'}
    
    if operation not in service_map:
        logger.error(f"❌ 未知的白名单操作: {operation}")
        return False if operation != 'list' else []
    
    try:
        params = {"authkey": CONFIG['PROXY_AUTH_KEY'], "service": service_map[operation], "format": "json"}
        if ip and operation in ('add', 'del'):
            params["white"] = ip
            
        result = await safe_request('get', CONFIG['PROXY_API_URL'], params=params)
        
        if result.get("ret") == 200:
            if operation == 'list':
                return result.get("data", [])
            else:
                action = "添加" if operation == "add" else "删除"
                logger.info(f"✅ 已{action} IP {ip} {'到' if operation == 'add' else '从'}白名单")
                return True
        else:
            error_msg = result.get('msg', '未知错误')
            logger.error(f"❌ IP 白名单{operation}操作失败: {error_msg}")
            return False if operation != 'list' else []
    except Exception as e:
        logger.error(f"❌ IP 白名单操作出错: {e}")
        return False if operation != 'list' else []

# ================ 青龙面板并发操作 ================
# 这些函数已被QingLongAPI类替代，保留注释以便理解代码历史
# async def fetch_panel_data(panel):
#     """获取单个青龙面板的数据 - 已被QingLongAPI类替代"""
#     pass

# async def clean_panel_cookies(panel_data):
#     """清理单个面板的非保留Cookies - 已被QingLongAPI类替代"""
#     pass

# ================ 定时任务 ================
async def update_ck():
    """更新 CK 任务"""
    try:
        logger.info("🔄 开始执行 CK 更新")
        # 使用QingLongAPI类获取CK
        ql_api = QingLongAPI(CONFIG['QL_URL'], CONFIG['CLIENT_ID'], CONFIG['CLIENT_SECRET'])
        cookies = await ql_api.get_enabled_cookies()
        
        if not cookies:
            logger.warning("⚠️ 未获取到有效 CK")
            return
            
        if await save_cookies_to_file(cookies):
            ck_hash = hashlib.sha256(json.dumps(cookies, sort_keys=True).encode('utf-8')).hexdigest()
            await redis_client.set(CONFIG['CURRENT_CK_HASH_KEY'], ck_hash)
            logger.info(f"✅ 已更新 {len(cookies)} 条 CK")
    except Exception as e:
        logger.error(f"❌ CK 更新出错: {e}", exc_info=True)

async def sync_ck_to_panels():
    """同步主青龙面板CK到其他面板"""
    try:
        logger.info("🔄 开始执行 CK 同步到其他面板")
        
        # 步骤1: 获取主青龙面板的CK（带备注）
        main_ql = QingLongAPI(CONFIG['QL_URL'], CONFIG['CLIENT_ID'], CONFIG['CLIENT_SECRET'])
        main_cookies_with_remarks = await main_ql.get_enabled_cookies_with_remarks()
        
        if not main_cookies_with_remarks:
            logger.warning("⚠️ 主青龙面板未获取到有效 CK")
            return
        
        logger.info(f"✅ 从主青龙面板获取到 {len(main_cookies_with_remarks)} 条有效CK")
        
        # 步骤2: 初始化所有面板的API客户端
        panel_apis = []
        for panel in CONFIG['QL_PANELS']:
            panel_apis.append(QingLongAPI(
                panel['url'], 
                panel['client_id'], 
                panel['client_secret'],
                name=panel['name']
            ))
        
        # 步骤3: 并行清理所有面板中的非保留Cookies
        async def clean_panel(api):
            try:
                # 获取所有CK
                cookies_info = await api.get_all_cookies()
                if not cookies_info:
                    return {
                        'name': api.name,
                        'success': True,
                        'message': "未发现CK",
                        'deleted_count': 0
                    }
                
                # 找出需要删除的CK（非保留名单）
                to_delete_ids = []
                preserved_pins = []
                
                for cookie in cookies_info:
                    pt_pin = extract_pt_pin(cookie['pt_pin'])
                    if should_preserve_cookie(pt_pin):
                        preserved_pins.append(pt_pin)
                    else:
                        to_delete_ids.append(cookie['id'])
                
                # 执行删除
                if to_delete_ids:
                    success, message = await api.delete_cookies(to_delete_ids)
                    if success:
                        return {
                            'name': api.name,
                            'success': True,
                            'message': f"已删除 {len(to_delete_ids)} 个非保留CK",
                            'deleted_count': len(to_delete_ids)
                        }
                    else:
                        return {
                            'name': api.name,
                            'success': False,
                            'message': f"删除失败 - {message}",
                            'deleted_count': 0
                        }
                else:
                    return {
                        'name': api.name,
                        'success': True,
                        'message': "没有需要删除的CK",
                        'deleted_count': 0
                    }
            except Exception as e:
                logger.error(f"❌ 清理面板 {api.name} CK出错: {e}")
                return {
                    'name': api.name,
                    'success': False,
                    'message': f"清理出错: {str(e)}",
                    'deleted_count': 0
                }
        
        # 并行执行清理
        clean_results = await asyncio.gather(*[clean_panel(api) for api in panel_apis])
        
        # 统计清理结果
        total_deleted = sum(result['deleted_count'] for result in clean_results if result['success'])
        logger.info(f"✅ 已从其他面板清理 {total_deleted} 条非保留CK")
        
        # 步骤4: 将主面板的CK添加到其他面板（保留原始备注）
        async def add_cookies_to_panel(api):
            try:
                success, message = await api.add_cookies(main_cookies_with_remarks)
                return {
                    'name': api.name,
                    'success': success,
                    'message': message
                }
            except Exception as e:
                logger.error(f"❌ 添加CK到面板 {api.name} 出错: {e}")
                return {
                    'name': api.name,
                    'success': False,
                    'message': f"添加出错: {str(e)}"
                }
        
        # 并行执行添加
        add_results = await asyncio.gather(*[add_cookies_to_panel(api) for api in panel_apis])
        
        # 统计添加结果
        success_count = sum(1 for result in add_results if result['success'])
        
        # 生成详细报告
        report = []
        for result in add_results:
            status = "✅" if result['success'] else "❌"
            report.append(f"{status} {result['name']}: {result['message']}")
        
        # 记录同步结果到日志，不发送通知
        logger.info(f"✅ CK同步任务完成，成功同步到 {success_count}/{len(panel_apis)} 个面板，同步了 {len(main_cookies_with_remarks)} 条CK，清理了 {total_deleted} 条非保留CK")
    except Exception as e:
        logger.error(f"❌ CK同步任务出错: {e}", exc_info=True)
        await notify("CK同步失败", str(e))

async def update_ip_whitelist():
    """更新 IP 白名单"""
    try:
        logger.info("🔄 开始检查 IP 白名单")
        current_ip = await get_current_ip()
        if not current_ip:
            logger.warning("⚠️ 获取当前IP失败")
            return
        
        old_ip = await redis_client.get(CONFIG['CURRENT_IP_KEY'])
        if current_ip == old_ip:
            logger.info("ℹ️ IP 未变动")
            return
        
        logger.info(f"🔔 IP 变动: {old_ip or '首次设置'} → {current_ip}")
        
        # 添加新IP到白名单
        add_success = await manage_whitelist('add', current_ip)
        if add_success:
            # 如果有旧IP，从白名单中删除
            if old_ip:
                del_success = await manage_whitelist('del', old_ip)
                if not del_success:
                    logger.warning(f"⚠️ 旧IP {old_ip} 删除失败，但不影响使用")
            
            # 更新Redis中的IP记录
            await redis_client.set(CONFIG['CURRENT_IP_KEY'], current_ip)
            
            # 发送通知
            await notify(
                "IP 白名单已更新",
                f"检测到 IP 变动，已自动更新白名单。\n旧 IP: {old_ip or '无'}\n新 IP: {current_ip}"
            )
            logger.info(f"✅ IP白名单已更新为: {current_ip}")
        else:
            logger.error("❌ 新IP添加失败，保留旧IP")
    except Exception as e:
        logger.error(f"❌ IP 白名单更新出错: {e}", exc_info=True)

async def cleanup_logs():
    """清理日志目录"""
    try:
        if os.path.exists(CONFIG['LOG_DIR']):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, shutil.rmtree, CONFIG['LOG_DIR'])
            os.makedirs(CONFIG['LOG_DIR'], exist_ok=True)
            logger.info(f"✅ 已清理日志目录: {CONFIG['LOG_DIR']}")
            await notify("日志清理完成", f"已清空目录: {CONFIG['LOG_DIR']}")
        else:
            logger.warning(f"⚠️ 日志目录不存在: {CONFIG['LOG_DIR']}")
    except Exception as e:
        logger.error(f"❌ 清理日志失败: {e}")
        await notify("日志清理失败", str(e))

# 任务调度器
async def run_task(task_func, name):
    """执行单个任务并处理异常"""
    try:
        await task_func()
    except Exception as e:
        logger.error(f"❌ {name}执行错误: {e}")

async def periodic_task(task_func, interval_minutes, name, run_immediately=True):
    """定期执行任务
    
    Args:
        task_func: 要执行的任务函数
        interval_minutes: 执行间隔（分钟）
        name: 任务名称
        run_immediately: 是否在启动时立即执行，默认为True
    """
    interval = interval_minutes * 60
    
    if not run_immediately:
        logger.info(f"⏱️ {name}将在 {interval_minutes} 分钟后首次执行")
        await asyncio.sleep(interval)
    
    while True:
        await run_task(task_func, name)
        logger.info(f"⏱️ {name}完成，{interval_minutes}分钟后再次执行")
        await asyncio.sleep(interval)

async def schedule_daily_task(hour, minute, task_func, name):
    """每日定时任务调度器"""
    while True:
        try:
            now = datetime.now(LOCAL_TIMEZONE)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if next_run < now:
                next_run += timedelta(days=1)
            
            wait_seconds = (next_run - now).total_seconds()
            logger.info(f"⏳ 下次{name}时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_seconds/3600:.2f} 小时")
            
            await asyncio.sleep(wait_seconds)
            await run_task(task_func, name)
        except Exception as e:
            logger.error(f"❌ 定时任务调度出错: {e}")
            await asyncio.sleep(60)

# ================ 机器人命令处理 ================
class CkWhitelistBot:
    def __init__(self, redis_client):
        self.redis_client = redis_client
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        logger.info(f"👤 用户 {update.effective_user.id} 发送了 /start")
        await update.message.reply_text(
            "👋 欢迎使用 CK 和白名单管理机器人！命令列表：\n\n"
            "🔹 /start - 显示命令列表\n"
            "🔹 /getck - 获取并保存 CK\n"
            "🔹 /ckstatus - 查看 CK 状态\n"
            "🔹 /ip <add|del|list|current> [IP] - 管理白名单\n"
            "🔹 /cleanlogs - 清理日志目录\n"
            "🔹 /zt - 查看系统状态\n"
            "🔹 /ql <list|clean> - 管理新增青龙面板的 CK\n"
            "🔹 /syncck - 手动执行CK同步到其他面板\n"
        )
    
    async def ck_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ckstatus 命令"""
        try:
            ck_count, ck_last_update_time = 0, "未知"
            
            if os.path.exists(CONFIG['CK_FILE_PATH']):
                with open(CONFIG['CK_FILE_PATH'], "r") as ck_file:
                    ck_count = sum(1 for line in ck_file if line.strip())
                ck_last_update = os.path.getmtime(CONFIG['CK_FILE_PATH'])
                ck_last_update_time = datetime.fromtimestamp(ck_last_update, LOCAL_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            
            await update.message.reply_text(
                "🍪 **CK 状态**\n\n"
                f"总数量: `{ck_count}`\n"
                f"最后更新时间: `{ck_last_update_time}`\n"
                f"存储路径: `{CONFIG['CK_FILE_PATH']}`\n",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ 获取 CK 状态出错: {e}")
    
    async def get_ck_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /getck 命令"""
        msg = await update.message.reply_text("🔄 正在获取 CK...")
        try:
            # 使用QingLongAPI类获取CK
            ql_api = QingLongAPI(CONFIG['QL_URL'], CONFIG['CLIENT_ID'], CONFIG['CLIENT_SECRET'])
            cookies = await ql_api.get_enabled_cookies()
            
            if not cookies:
                await msg.edit_text("⚠️ 未获取到有效的 CK")
                return
                
            if await save_cookies_to_file(cookies):
                ck_hash = hashlib.sha256(json.dumps(cookies, sort_keys=True).encode('utf-8')).hexdigest()
                await self.redis_client.set(CONFIG['CURRENT_CK_HASH_KEY'], ck_hash)
                await msg.edit_text(f"✅ 已成功获取并保存 {len(cookies)} 条 CK")
            else:
                await msg.edit_text("❌ CK 保存失败")
        except Exception as e:
            logger.error(f"❌ 获取 CK 出错: {e}", exc_info=True)
            await msg.edit_text(f"❌ 获取 CK 出错: {str(e)}")
    
    async def manage_ip_whitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ip 命令"""
        if not context.args:
            await update.message.reply_text(
                "❌ 使用格式:\n"
                "/ip add IP - 添加IP到白名单\n"
                "/ip del IP - 从白名单删除IP\n"
                "/ip list - 查看白名单\n"
                "/ip current - 添加当前IP到白名单"
            )
            return

        cmd = context.args[0].lower()
        msg = await update.message.reply_text("🔄 处理中...")
        
        try:
            if cmd == "list":
                ip_list = await manage_whitelist('list')
                text = "📃 当前IP白名单:\n" + "\n".join(f"• {ip}" for ip in ip_list) if ip_list else "📃 白名单为空"
                await msg.edit_text(text)
                
            elif cmd == "current":
                ip = await get_current_ip()
                if not ip:
                    await msg.edit_text("❌ 获取当前 IP 失败")
                    return
                
                success = await manage_whitelist('add', ip)
                await msg.edit_text(f"{'✅ 已添加' if success else '❌ 添加失败'} IP: {ip}")
                
            elif cmd in ["add", "del"]:
                if len(context.args) <= 1:
                    await msg.edit_text(f"❌ 请提供要{'添加' if cmd == 'add' else '删除'}的 IP")
                    return
                    
                ip = context.args[1]
                success = await manage_whitelist(cmd, ip)
                await msg.edit_text(f"{'✅ 已' + ('添加' if cmd == 'add' else '删除') if success else '❌ ' + ('添加' if cmd == 'add' else '删除') + '失败'} IP: {ip}")
                
            else:
                await msg.edit_text("❌ 未知命令")
                
        except Exception as e:
            await msg.edit_text(f"❌ 操作失败: {e}")      

    async def clean_logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /cleanlogs 命令"""
        msg = await update.message.reply_text("🔄 正在清理日志...")
        try:
            await cleanup_logs()
            await msg.edit_text("✅ 日志清理完成")
        except Exception as e:
            await msg.edit_text(f"❌ 清理失败: {e}")

    async def get_system_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /zt 命令，获取系统状态"""
        msg = await update.message.reply_text("🔄 正在获取系统状态...")
        
        try:
            # 系统信息
            system_info = {
                "系统": f"{platform.system()} {platform.version()}",
                "架构": platform.machine(),
                "主机名": platform.node(),
                "Python版本": platform.python_version()
            }
            
            # 获取系统启动时间
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            days, seconds = uptime.days, uptime.seconds
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            
            # CPU信息
            cpu_info = {
                "CPU核心数": psutil.cpu_count(logical=False),
                "逻辑CPU数": psutil.cpu_count(logical=True),
                "CPU使用率": f"{psutil.cpu_percent(interval=0.5)}%",
                "CPU频率": f"{psutil.cpu_freq().current:.2f} MHz" if psutil.cpu_freq() else "未知"
            }
            
            # 内存信息
            memory = psutil.virtual_memory()
            memory_info = {
                "总内存": f"{memory.total / (1024 ** 3):.2f} GB",
                "可用内存": f"{memory.available / (1024 ** 3):.2f} GB",
                "内存使用率": f"{memory.percent}%"
            }
            
            # 交换分区信息
            swap = psutil.swap_memory()
            swap_info = {
                "总交换空间": f"{swap.total / (1024 ** 3):.2f} GB",
                "已用交换空间": f"{swap.used / (1024 ** 3):.2f} GB",
                "交换空间使用率": f"{swap.percent}%"
            }
            
            # 磁盘信息
            disk = psutil.disk_usage('/')
            disk_info = {
                "总空间": f"{disk.total / (1024 ** 3):.2f} GB",
                "可用空间": f"{disk.free / (1024 ** 3):.2f} GB",
                "磁盘使用率": f"{disk.percent}%"
            }
            
            # 网络信息
            net_io = psutil.net_io_counters()
            net_info = {
                "已发送": f"{net_io.bytes_sent / (1024 ** 3):.2f} GB",
                "已接收": f"{net_io.bytes_recv / (1024 ** 3):.2f} GB"
            }
            
            # 尝试获取TCP连接信息
            try:
                tcp_connections = len(psutil.net_connections(kind='tcp'))
                tcp_established = len([c for c in psutil.net_connections(kind='tcp') if c.status == 'ESTABLISHED'])
                tcp_listen = len([c for c in psutil.net_connections(kind='tcp') if c.status == 'LISTEN'])
                tcp_info = {
                    "TCP连接总数": tcp_connections,
                    "已建立连接": tcp_established,
                    "监听连接": tcp_listen
                }
            except psutil.AccessDenied:
                tcp_info = {"TCP连接信息": "无法获取（权限不足）"}
            
            # Node.js进程数量
            node_count = len([proc for proc in psutil.process_iter(['name']) 
                             if 'node' in proc.info['name'].lower()])
            
            # 格式化输出
            status_text = (
                "📊 **系统状态**\n\n"
                "🖥️ **系统信息**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in system_info.items()) +
                f"\n• 运行时间: `{days}天{hours}时{minutes}分`" +
                "\n\n🔄 **CPU信息**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in cpu_info.items()) +
                "\n\n💾 **内存信息**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in memory_info.items()) +
                "\n\n🔄 **交换分区**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in swap_info.items()) +
                "\n\n💽 **磁盘信息**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in disk_info.items()) +
                "\n\n🌐 **网络信息**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in net_info.items()) +
                "\n\n🔌 **连接信息**\n" + 
                "\n".join(f"• {k}: `{v}`" for k, v in tcp_info.items()) +
                f"\n\n🟢 **Node.js进程**: `{node_count}个`\n"
            )
            
            await msg.edit_text(status_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"❌ 获取系统状态出错: {e}")
            await msg.edit_text(f"❌ 获取系统状态出错: {e}")

    async def manage_ql_cookies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ql 命令，管理新增青龙面板的Cookies"""
        if not context.args:
            await update.message.reply_text(
                "❌ 使用格式:\n"
                "/ql list - 查看所有新增青龙面板的CK状态\n"
                "/ql clean - 清理新增面板中的CK（保留指定的pt_pin）"
            )
            return

        cmd = context.args[0].lower()
        msg = await update.message.reply_text("🔄 正在处理青龙面板...")
        
        try:
            # 确保只处理QL_PANELS中的面板，不处理主面板
            if not CONFIG['QL_PANELS']:
                await msg.edit_text("⚠️ 未配置任何新增青龙面板，请先在CONFIG中添加QL_PANELS配置")
                return
            
            # 初始化所有面板的API客户端
            panel_apis = [QingLongAPI(
                panel['url'], 
                panel['client_id'], 
                panel['client_secret'],
                name=panel['name']
            ) for panel in CONFIG['QL_PANELS']]
        
            if cmd == "list":
                # 并行获取所有面板数据
                async def get_panel_info(api):
                    try:
                        cookies_info = await api.get_all_cookies()
                        return {
                            'name': api.name,
                            'success': True,
                            'cookies_info': cookies_info
                        }
                    except Exception as e:
                        logger.error(f"❌ 获取面板{api.name}数据失败: {e}")
                        return {
                            'name': api.name,
                            'success': False,
                            'error': str(e),
                            'cookies_info': []
                        }
                
                panels_data = await asyncio.gather(*[get_panel_info(api) for api in panel_apis])
                
                result_text = "📃 **新增青龙面板CK状态**\n\n"
                
                # 添加总体统计
                total_cookies = sum(len(p['cookies_info']) for p in panels_data if p['success'])
                result_text += f"面板: {len(panels_data)}个\n\n"
                
                # 遍历每个面板
                for panel_data in panels_data:
                    if not panel_data['success']:
                        result_text += f"⚠️ **{panel_data['name']}**: 连接失败\n"
                        continue
                    
                    cookies_info = panel_data['cookies_info']
                    if not cookies_info:
                        result_text += f"ℹ️ **{panel_data['name']}**: 未发现CK\n"
                        continue
                    
                    # 统计信息
                    enabled_count = sum(1 for c in cookies_info if c['status'] == 0)
                    disabled_count = sum(1 for c in cookies_info if c['status'] == 1)
                    preserved_count = sum(1 for c in cookies_info if should_preserve_cookie(extract_pt_pin(c['pt_pin'])))
                    
                    result_text += f"🔹 **{panel_data['name']}**: "
                    result_text += f"总数{len(cookies_info)} 启用{enabled_count} 禁用{disabled_count} 保留{preserved_count}\n"
                
                # 显示保留的pt_pin列表
                result_text += "\n⭐ **保留名单**:\n"
                preserved_pins = [pin.replace("pt_pin=", "").strip(';') for pin in CONFIG['PRESERVED_PT_PINS'] if pin]
                result_text += ", ".join(f"`{pin}`" for pin in preserved_pins) if preserved_pins else "无保留账号"
                
                await msg.edit_text(result_text, parse_mode="Markdown")
                
            elif cmd == "clean":
                # 使用sync_ck_to_panels中定义的clean_panel函数
                async def clean_panel(api):
                    try:
                        # 获取所有CK
                        cookies_info = await api.get_all_cookies()
                        if not cookies_info:
                            return {
                                'name': api.name,
                                'success': True,
                                'message': "未发现CK",
                                'deleted_count': 0
                            }
                        
                        # 找出需要删除的CK（非保留名单）
                        to_delete_ids = []
                        preserved_pins = []
                        
                        for cookie in cookies_info:
                            pt_pin = extract_pt_pin(cookie['pt_pin'])
                            if should_preserve_cookie(pt_pin):
                                preserved_pins.append(pt_pin)
                            else:
                                to_delete_ids.append(cookie['id'])
                        
                        # 执行删除
                        if to_delete_ids:
                            success, message = await api.delete_cookies(to_delete_ids)
                            if success:
                                return {
                                    'name': api.name,
                                    'success': True,
                                    'message': f"已删除 {len(to_delete_ids)} 个非保留CK",
                                    'deleted_count': len(to_delete_ids)
                                }
                            else:
                                return {
                                    'name': api.name,
                                    'success': False,
                                    'message': f"删除失败 - {message}",
                                    'deleted_count': 0
                                }
                        else:
                            return {
                                'name': api.name,
                                'success': True,
                                'message': "没有需要删除的CK",
                                'deleted_count': 0
                            }
                    except Exception as e:
                        logger.error(f"❌ 清理面板 {api.name} CK出错: {e}")
                        return {
                            'name': api.name,
                            'success': False,
                            'message': f"清理出错: {str(e)}",
                            'deleted_count': 0
                        }
                
                # 并行执行清理
                clean_results = await asyncio.gather(*[clean_panel(api) for api in panel_apis])
                
                # 处理结果
                result_text = "🧹 **清理结果**\n\n"
                total_deleted = 0
                
                for result in clean_results:
                    if result['success']:
                        if result['deleted_count'] > 0:
                            result_text += f"✅ **{result['name']}**: {result['message']}\n"
                        else:
                            result_text += f"ℹ️ **{result['name']}**: {result['message']}\n"
                        total_deleted += result['deleted_count']
                    else:
                        result_text += f"❌ **{result['name']}**: {result['message']}\n"
                
                result_text += f"\n📊 **总删除数**: {total_deleted}\n"
                await msg.edit_text(result_text, parse_mode="Markdown")
                
            else:
                await msg.edit_text(f"❌ 未知命令: {cmd}")
                
        except Exception as e:
            logger.error(f"❌ 管理青龙面板CK出错: {e}", exc_info=True)
            await msg.edit_text(f"❌ 操作失败: {str(e)}")
            
    async def sync_ck_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /syncck 命令，手动执行CK同步到其他面板"""
        msg = await update.message.reply_text("🔄 正在执行CK同步到其他面板...")
        try:
            # 执行同步并捕获详细结果
            await sync_ck_to_panels()
            
            # 获取最新的同步状态
            main_ql = QingLongAPI(CONFIG['QL_URL'], CONFIG['CLIENT_ID'], CONFIG['CLIENT_SECRET'])
            main_cookies = await main_ql.get_enabled_cookies()
            
            # 构建详细的状态报告
            status_text = f"✅ CK同步操作已完成\n\n主面板CK数量: {len(main_cookies)}个"
            
            await msg.edit_text(status_text)
        except Exception as e:
            logger.error(f"❌ 手动同步CK出错: {e}", exc_info=True)
            await msg.edit_text(f"❌ 同步失败: {str(e)}")

# ================ 主程序 ================
async def main():
    try:
        # 设置日志
        await setup_logging()
        
        # 初始化Redis客户端
        global redis_client
        redis_client = StrictRedis(
            host=CONFIG['REDIS_HOST'], 
            port=CONFIG['REDIS_PORT'], 
            db=CONFIG['REDIS_DB'], 
            password=CONFIG['REDIS_PASSWORD'], 
            decode_responses=True,
            socket_timeout=10, 
            socket_connect_timeout=10
        )
        
        logger.info(f"✅ 已从配置文件加载配置")
        
        # 初始化 bot
        base_url = CONFIG['TELEGRAM_PROXY_API'].rstrip('/')
        logger.info(f"🔌 连接到 API: {base_url}")
        
        # 测试连接
        try:
            test_url = f"{base_url}/bot{CONFIG['TELEGRAM_TOKEN']}/getMe"
            bot_info = await safe_request('get', test_url)
            
            if bot_info.get("ok"):
                bot_username = bot_info.get('result', {}).get('username')
                logger.info(f"✅ 连接成功: @{bot_username}")
            else:
                logger.error(f"❌ API 错误: {bot_info}")
                return
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            return       
        
        # 创建bot应用
        bot = CkWhitelistBot(redis_client)
        application = (
            ApplicationBuilder()
            .base_url(f"{base_url}/bot")
            .token(CONFIG['TELEGRAM_TOKEN'])
            .build()
        )
        
        # 注册命令
        application.add_handler(CommandHandler("start", bot.start))
        application.add_handler(CommandHandler("getck", bot.get_ck_command))
        application.add_handler(CommandHandler("ckstatus", bot.ck_status))
        application.add_handler(CommandHandler("ip", bot.manage_ip_whitelist))
        application.add_handler(CommandHandler("cleanlogs", bot.clean_logs_command))
        application.add_handler(CommandHandler("zt", bot.get_system_status))
        application.add_handler(CommandHandler("ql", bot.manage_ql_cookies))
        application.add_handler(CommandHandler("syncck", bot.sync_ck_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, 
                                             lambda u, c: logger.info(f"📨 收到消息: {u.message.text[:20]}...")))
        
        # 启动应用
        await application.initialize()
        await application.start()
        await application.updater.start_polling(poll_interval=1.0, drop_pending_updates=True)
        logger.info("🚀 机器人已启动，可接收命令")
        
        # 向管理员发送通知
        admin_id = CONFIG['TG_USER_IDS'][0] if CONFIG['TG_USER_IDS'] else None
        if admin_id:
            await application.bot.send_message(
                chat_id=admin_id, 
                text="✅ CK和白名单管理程序已启动，可接收命令"
            )
        
        # 启动定时任务，不在启动时立即执行CK同步，而是按照配置的时间间隔执行
        tasks = [
            periodic_task(update_ck, CONFIG['CK_UPDATE_INTERVAL'], "CK 更新"),
            periodic_task(update_ip_whitelist, CONFIG['IP_UPDATE_INTERVAL'], "IP 白名单更新"),
            periodic_task(sync_ck_to_panels, CONFIG['CK_SYNC_INTERVAL'], "CK 同步到其他面板", run_immediately=False),
            schedule_daily_task(23, 59, cleanup_logs, "日志清理")
        ]
        await asyncio.gather(*[asyncio.create_task(task) for task in tasks])
            
    except Exception as e:
        logger.error(f"❌ 启动失败: {e}", exc_info=True)

if __name__ == "__main__":
    print("\033[1;36m===== 正在启动 CK 和白名单管理程序 =====\033[0m")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
    except Exception as e:
        print(f"\033[91m❌ 程序错误: {e}\033[0m")