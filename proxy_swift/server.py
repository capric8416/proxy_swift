# -*- coding: utf-8 -*-
# !/usr/bin/env python

import asyncio
import inspect
import json
import os
import time
import uuid
from datetime import datetime
from urllib import parse

import aioredis
from aiohttp import web
from aiohttp_session import get_session, setup
from aiohttp_session.redis_storage import RedisStorage

from .client import AsyncProxyClient
from .logger import get_logger

MAX_AGE = 3600
PROXY_CLIENT = None
LOGGER = get_logger(name=__name__)
REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379'


class RedisPool(object):
    _pool = {}

    @classmethod
    async def get(cls, url):
        """获取redis连接池，如果没有则创建"""

        LOGGER.info(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        if url in cls._pool:
            return cls._pool[url]

        p = parse.urlparse(url=url)
        pool = await aioredis.create_pool(address=(p.hostname, p.port), password=p.password)
        cls._pool[url] = pool

        return pool

    @classmethod
    def key(cls, *args):
        LOGGER.debug(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        if len(args) > 1:
            args = list(args)
            max_len = len(args[0])
            for i in range(1, len(args)):
                if not args[i]:
                    continue
                args[i] += '_' * (max_len - len(args[i]))
        return ':'.join(args)


class RedisKey(object):
    _prefix = '5zhlyuNOwJ'
    _ip = 'ip'
    _cookie = 'aiohttp'
    _proxy = 'proxy'
    _interface = 'interface'

    cookie = RedisPool.key(_prefix, _cookie, 'cookies', 'string', '')  # string

    my_used_ip = RedisPool.key(_prefix, _ip, 'my_used', 'set', '')  # set
    all_used_ip = RedisPool.key(_prefix, _ip, 'all_used', 'set')  # set

    available_proxy = RedisPool.key(_prefix, _proxy, 'available', 'hash')  # hash

    all_interface = RedisPool.key(_prefix, _interface, 'all', 'set')  # set
    used_interface = RedisPool.key(_prefix, _interface, 'used', 'set')  # set
    running_interface = RedisPool.key(_prefix, _interface, 'running', 'hash')  # hash
    available_interface = RedisPool.key(_prefix, _interface, 'available', 'set')  # set


class ProxyView(web.View):
    @property
    def loop(self):
        """获取事件循环"""
        return self.request.app.loop

    @staticmethod
    def timestamp():
        """获取当前时间戳"""
        return int(time.mktime(datetime.now().timetuple()))

    @classmethod
    async def interfaces(cls):
        """获取所有的代理ID"""
        LOGGER.info(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            return {int(item) for item in await cls.execute(redis, 'smembers', RedisKey.all_interface)}

    @classmethod
    async def get_ip(cls, pool_id=3, interface_id=None):
        """获取所有的IP"""
        LOGGER.info(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        return await PROXY_CLIENT.get_ip(pool_id=pool_id, interface_id=interface_id)

    @classmethod
    async def change_ip(cls, pool_id=3, interface_id=None):
        """更换IP"""
        LOGGER.info(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        if interface_id:
            return await PROXY_CLIENT.change_ip(pool_id=pool_id, interface_id=interface_id)
        else:
            return await asyncio.gather(*[
                PROXY_CLIENT.change_ip(pool_id=pool_id, interface_id=interface_id)
                for interface_id in await cls.interfaces()
            ])

    async def get_session_identity(self):
        """获取session和标识，如果没有则创建"""
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        session = await get_session(request=self.request)
        if not session.identity:
            session['identity'] = session._identity = uuid.uuid4().hex

        return session, session.identity

    @classmethod
    async def execute(cls, redis, command, *args):
        """执行redis指令"""
        LOGGER.debug(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        return await redis.connection.execute(command, *args)

    @classmethod
    async def multi_execute(cls, redis, *commands):
        """批量执行redis指令"""
        LOGGER.debug(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        redis.connection.execute('multi')
        for command in commands:
            redis.connection.execute(*command)
        return await redis.connection.execute('exec')

    @classmethod
    async def expire(cls, redis, key, seconds):
        """设置key过期时间"""
        LOGGER.debug(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        ttl = await cls.execute(redis, 'ttl', key)
        if ttl == -1:
            await cls.execute(redis, 'expire', key, seconds)

    async def update_all_proxy(self, redis, items):
        """更新可用代理，已用代理ID，所有IP"""
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        await asyncio.gather(*[self._update_all_proxy(redis=redis, item=item) for item in items])

    @classmethod
    async def _update_all_proxy(cls, redis, item):
        await cls.multi_execute(
            redis, *[
                ('srem', RedisKey.used_interface, item['id']),
                ('hdel', RedisKey.running_interface, item['id']),
                ('sadd', RedisKey.available_interface, item['id']),
                ('hset', RedisKey.available_proxy, item['id'], json.dumps(item)),
                ('sadd', RedisKey.all_used_ip, item['ip'])
            ]
        )

    @classmethod
    async def update_one_proxy(cls, redis, key_my_proxy, current_proxy, last_interface):
        """更新在用代理ID，已用的代理ID, 我的已用IP"""
        LOGGER.info(f'{cls.__name__}.{inspect.currentframe().f_code.co_name}')

        commands = [
            ('hset', RedisKey.running_interface, current_proxy['id'], cls.timestamp()),
            ('hdel', RedisKey.available_proxy, current_proxy['id']),
            ('sadd', key_my_proxy, current_proxy['ip']),
            ('sadd', RedisKey.all_used_ip, current_proxy['ip'])
        ]
        if last_interface:
            commands.insert(0, ('sadd', RedisKey.used_interface, last_interface))
            commands.insert(1, ('hdel', RedisKey.running_interface, last_interface))

        await cls.multi_execute(redis, *commands)
        await cls.expire(redis=redis, key=key_my_proxy, seconds=MAX_AGE)


class GetIpView(ProxyView):
    async def get(self):
        """获取IP"""
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        session, identity = await self.get_session_identity()
        key_my_proxy = f'{RedisKey.my_used_ip}_{identity}'

        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            for i in range(10):
                interface = await self.execute(redis, 'spop', RedisKey.available_interface)
                if not interface:
                    await asyncio.sleep(i % 2 + 1)
                    continue

                proxy = await self.execute(redis, 'hget', RedisKey.available_proxy, interface)
                _proxy = json.loads(proxy)

                if await self.execute(redis, 'sismember', key_my_proxy, _proxy['ip']):
                    await self.execute(redis, 'sadd', RedisKey.available_interface, _proxy['ip'])
                else:
                    await self.update_one_proxy(
                        redis=redis, key_my_proxy=key_my_proxy, current_proxy=_proxy,
                        last_interface=session.get('last_interface'))

                    session['last_interface'] = _proxy['id']

                    return web.json_response(text=proxy.decode())

        return web.json_response(text='{}')


class BlockIpView(ProxyView):
    async def get(self):
        """拉黑IP"""
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            identity = await self.get_session_identity()

            ip = self.request.query.get('ip')
            if ip:
                key = f'{RedisKey.my_used_ip}_{identity}'
                await self.execute(redis, 'sadd', key, ip)
                await self.expire(redis=redis, key=key, seconds=MAX_AGE)

        return web.json_response({})


class RestartView(ProxyView):
    async def get(self):
        """获取/刷新IP"""
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            keys = [RedisKey.available_interface, RedisKey.all_interface,
                    RedisKey.used_interface, RedisKey.running_interface, RedisKey.available_proxy]
            keys += await self.execute(redis, 'keys', RedisKey.cookie + '*')
            keys += await self.execute(redis, 'keys', RedisKey.my_used_ip + '*')
            await self.execute(redis, 'del', *keys)

            _proxy = [item for item in await self.get_ip() if item['id'] <= 56]

            await self.execute(redis, 'sadd', RedisKey.all_interface, *[item['id'] for item in _proxy])

            if self.request.query.get('full'):
                _proxy = await self.change_ip()

            await self.update_all_proxy(redis=redis, items=_proxy)

        return web.json_response({})


class BackgroundTasks(object):
    def __init__(self):
        self.redis = None

        self.execute = ProxyView.execute
        self.multi_execute = ProxyView.multi_execute
        self.timestamp = ProxyView.timestamp
        # self.get_ip = ProxyView.get_ip
        self.change_ip = ProxyView.change_ip

        self.tasks = ['check_proxy']

    async def _change_ip(self, interface):
        """更换IP"""
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        await self.execute(self.redis, 'srem', RedisKey.used_interface, interface)

        proxy = await self.change_ip(interface_id=interface)
        # proxy = await self.get_ip(interface_id=interface)

        await self.multi_execute(
            self.redis, *[
                ('sadd', RedisKey.available_interface, interface),
                ('hset', RedisKey.available_proxy, interface, json.dumps(proxy)),
                ('hdel', RedisKey.running_interface, interface)
            ]
        )

    async def _drop_ip(self, interface, timestamp):
        """丢弃IP"""
        LOGGER.debug(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        if self.timestamp() - timestamp > MAX_AGE:
            await self.multi_execute(
                self.redis, *[
                    ('hdel', RedisKey.running_interface, interface),
                    ('hdel', RedisKey.available_proxy, interface),
                    ('srem', RedisKey.available_interface, interface),
                    ('sadd', RedisKey.used_interface, interface)
                ]
            )

    async def _check_used(self):
        """为使用过的代理ID更换IP"""
        LOGGER.debug(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        interfaces = await self.execute(self.redis, 'smembers', RedisKey.used_interface)
        if interfaces:
            await asyncio.gather(*[self._change_ip(interface=int(interface)) for interface in interfaces])

    async def _check_running(self):
        """为正在使用的但超时代理ID更换IP"""
        LOGGER.debug(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        interfaces = await self.execute(self.redis, 'hgetall', RedisKey.running_interface)
        if interfaces:
            await asyncio.gather(*[
                self._drop_ip(interface=int(interfaces[index]), timestamp=int(interfaces[index + 1]))
                for index in range(0, len(interfaces), 2)
            ])

    async def check_proxy(self):
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            self.redis = redis
            while True:
                try:
                    await asyncio.gather(self._check_used(), self._check_running())
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break

    async def start(self, app):
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        for task in self.tasks:
            app[task] = app.loop.create_task(getattr(self, task)())

    async def cleanup(self, app):
        LOGGER.info(f'{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}')

        app['redis_pool'].close()
        await app['redis_pool'].wait_closed()

        for task in self.tasks:
            app[task].cancel()
            await app[task]


class AsyncProxyServer(object):
    @staticmethod
    def run(secret_key, partner_id, host='127.0.0.1', port=8080):
        # 获取事件循环
        event_loop = asyncio.get_event_loop()

        # 获取redis连接池
        redis_pool = event_loop.run_until_complete(RedisPool.get(url=REDIS_URL))

        # 初始化代理客户端
        global PROXY_CLIENT
        PROXY_CLIENT = AsyncProxyClient(secret_key=secret_key, partner_id=partner_id)

        # 初始化app
        app = web.Application(loop=event_loop)
        app['redis_pool'] = redis_pool

        # 设置cookie存储
        setup(app, RedisStorage(redis_pool=redis_pool, cookie_name=RedisKey.cookie, max_age=MAX_AGE))

        # 设置url映射
        app.router.add_route('*', '/get/ip', GetIpView)
        app.router.add_route('*', '/block/ip', BlockIpView)
        app.router.add_route('*', '/restart', RestartView)

        # 后台任务
        background_tasks = BackgroundTasks()
        app.on_startup.append(background_tasks.start)
        app.on_cleanup.append(background_tasks.cleanup)

        # 启动app
        web.run_app(app=app, host=host, port=port)
