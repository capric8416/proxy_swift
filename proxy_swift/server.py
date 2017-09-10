# -*- coding: utf-8 -*-
# !/usr/bin/env python

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from urllib import parse

import aioredis
import client
from aiohttp import web
from aiohttp_session import setup, get_session
from aiohttp_session.redis_storage import RedisStorage

MAX_AGE = 3600

REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379'
REDIS_KEY_COOKIE = 'aio_http_proxy_cookies'
REDIS_KEY_ALL_IP = 'aio_http_ip_all'
REDIS_KEY_MY_PROXY = 'aio_http_proxy_my'
REDIS_KEY_AVAILABLE_PROXY = 'aio_http_proxy_available'
REDIS_KEY_ALL_INTERFACE = 'aio_http_interface_all'
REDIS_KEY_USED_INTERFACE = 'aio_http_proxy_used'
REDIS_KEY_RUNNING_INTERFACE = 'aio_http_proxy_running'

BACKGROUND_TASKS = ('check_used_proxy', 'check_running_proxy')

PROXY_CLIENT = client.AsyncProxySwift(secret_key='Kg6t55fc39FQRJuh92BwZBMXyK3sWFkJ', partner_id='2017072514450843')


class RedisPool(object):
    _pool = {}

    @classmethod
    async def get(cls, url):
        """获取redis连接池，如果没有则创建"""
        if url in cls._pool:
            return cls._pool[url]

        p = parse.urlparse(url=url)
        pool = await aioredis.create_pool(address=(p.hostname, p.port), password=p.password)
        cls._pool[url] = pool

        return pool


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
        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            return {int(item) for item in await cls.execute(redis, 'smembers', REDIS_KEY_ALL_INTERFACE)}

    @staticmethod
    async def get_ip(pool_id=3):
        """获取所有的IP"""
        return await PROXY_CLIENT.get_ip(pool_id=pool_id)

    @classmethod
    async def change_ip(cls, pool_id=3, interface_id=None):
        """更换IP"""
        if interface_id:
            return await PROXY_CLIENT.change_ip(pool_id=pool_id, interface_id=interface_id)
        else:
            return await asyncio.gather(*[
                PROXY_CLIENT.change_ip(pool_id=pool_id, interface_id=interface_id)
                for interface_id in await cls.interfaces()
            ])

    async def get_session_identity(self):
        """获取session和标识，如果没有则创建"""
        session = await get_session(request=self.request)
        if not session.identity:
            session['identity'] = session._identity = uuid.uuid4().hex

        return session, session.identity

    @staticmethod
    async def execute(redis, command, *args):
        """执行redis指令"""
        return await redis.connection.execute(command, *args)

    @classmethod
    async def expire(cls, redis, key, seconds):
        """设置key过期时间"""
        ttl = await cls.execute(redis, 'ttl', key)
        if ttl == -1:
            await cls.execute(redis, 'expire', key, seconds)

    async def update_all_proxy(self, redis, items):
        """更新可用代理，已用代理ID，所有IP"""
        await asyncio.gather(*[self._update_all_proxy(redis=redis, item=item) for item in items])

    @classmethod
    async def _update_all_proxy(cls, redis, item):
        await cls.execute(redis, 'srem', REDIS_KEY_USED_INTERFACE, item['id'])
        await cls.execute(redis, 'hdel', REDIS_KEY_RUNNING_INTERFACE, item['id'])
        await cls.execute(redis, 'rpush', REDIS_KEY_AVAILABLE_PROXY, json.dumps(obj=item))
        await cls.execute(redis, 'sadd', REDIS_KEY_ALL_IP, item['ip'])

    @classmethod
    async def update_one_proxy(cls, redis, key, proxy, last):
        """更新在用代理ID，已用的代理ID, 我的已用IP"""
        await cls.execute(redis, 'srem', REDIS_KEY_USED_INTERFACE, last)
        await cls.execute(redis, 'hset', REDIS_KEY_RUNNING_INTERFACE, proxy['id'], cls.timestamp())
        await cls.execute(redis, 'sadd', key, proxy['ip'])
        await cls.expire(redis=redis, key=key, seconds=MAX_AGE)


class GetIpView(ProxyView):
    async def get(self):
        """获取IP"""
        session, identity = await self.get_session_identity()
        key = f'{REDIS_KEY_MY_PROXY}_{identity}'

        proxy = '{}'
        _proxy = {}

        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            for _ in range(10):
                proxy = await self.execute(redis, 'lpop', REDIS_KEY_AVAILABLE_PROXY)
                if not proxy:
                    return web.json_response({})

                _proxy = json.loads(proxy)

                if await self.execute(redis, 'sismember', key, _proxy['ip']):
                    await self.execute(redis, 'rpush', REDIS_KEY_AVAILABLE_PROXY, proxy)
                else:
                    break

            await self.update_one_proxy(redis=redis, key=key, proxy=_proxy, last=_proxy['id'])

            session['last'] = _proxy['id']

        return web.json_response(text=proxy.decode())


class BlockIpView(ProxyView):
    async def get(self):
        """拉黑IP"""
        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            identity = await self.get_session_identity()

            ip = self.request.query.get('ip')
            if ip:
                key = f'{REDIS_KEY_MY_PROXY}_{identity}'
                await self.execute(redis, 'sadd', key, ip)
                await self.expire(redis=redis, key=key, seconds=MAX_AGE)

        return web.json_response({})


class RestartView(ProxyView):
    async def get(self):
        """获取/刷新IP"""
        pool = await RedisPool.get(url=REDIS_URL)
        with await pool as redis:
            await self.execute(redis, 'del', REDIS_KEY_ALL_INTERFACE, REDIS_KEY_AVAILABLE_PROXY, REDIS_KEY_COOKIE)

            _proxy = [item for item in await self.get_ip() if item['id'] <= 56]

            await self.execute(redis, 'sadd', REDIS_KEY_ALL_INTERFACE, *[item['id'] for item in _proxy[:1]])

            if self.request.query.get('full'):
                _proxy = await self.change_ip()

            await self.update_all_proxy(redis=redis, items=_proxy)

        return web.json_response({})


async def check_used_proxy():
    """为使用过的代理ID更换IP"""

    async def _change_ip(_redis, _interface):
        proxy = await ProxyView.change_ip(interface_id=_interface)
        await ProxyView.execute(_redis, 'rpush', REDIS_KEY_AVAILABLE_PROXY, json.dumps(proxy))
        await ProxyView.execute(_redis, 'hdel', REDIS_KEY_RUNNING_INTERFACE, _interface)
        await ProxyView.execute(_redis, 'srem', REDIS_KEY_USED_INTERFACE, _interface)

    pool = await RedisPool.get(url=REDIS_URL)
    with await pool as redis:
        while True:
            try:
                await asyncio.gather(*[
                    _change_ip(_redis=redis, _interface=interface)
                    for interface in await ProxyView.execute(redis=redis, command='smembers')
                ])
                asyncio.sleep(1)
            except asyncio.CancelledError:
                break


async def check_running_proxy():
    """为正在使用的但超时代理ID更换IP"""

    async def _drop_ip(_redis, _interface, _timestamp):
        if ProxyView.timestamp() - _timestamp > MAX_AGE:
            await ProxyView.execute(_redis, 'hdel', REDIS_KEY_RUNNING_INTERFACE, _interface)
            await ProxyView.execute(_redis, 'sadd', REDIS_KEY_USED_INTERFACE, _interface)

    pool = await RedisPool.get(url=REDIS_URL)
    with await pool as redis:
        while True:
            try:
                interfaces = await ProxyView.execute(redis=redis, command='hgetall')
                await asyncio.gather(*[
                    _drop_ip(_redis=redis, _interface=interface, _timestamp=int(timestamp))
                    for interface, timestamp in interfaces.items()
                ])

                asyncio.sleep(1)
            except asyncio.CancelledError:
                break


async def start_background_tasks(app):
    for task in BACKGROUND_TASKS:
        app[task] = app.loop.create_task(globals()[task]())


async def cleanup_background_tasks(app):
    for task in BACKGROUND_TASKS:
        app[task].cancel()
        await app[task]


def run_app(event_loop, redis_pool):
    # 初始化app
    app = web.Application(loop=event_loop)

    # 设置cookie存储
    setup(app, RedisStorage(redis_pool=redis_pool, cookie_name=REDIS_KEY_COOKIE, max_age=MAX_AGE))

    # 设置url映射
    app.router.add_route('*', '/get/ip', GetIpView)
    app.router.add_route('*', '/block/ip', BlockIpView)
    app.router.add_route('*', '/restart', RestartView)

    # 后台任务
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    # 启动app
    web.run_app(app)


if __name__ == '__main__':
    # 获取事件循环
    _loop = asyncio.get_event_loop()
    # 获取redis连接池
    _pool = _loop.run_until_complete(RedisPool.get(url=REDIS_URL))
    # 启动web服务
    run_app(event_loop=_loop, redis_pool=_pool)
