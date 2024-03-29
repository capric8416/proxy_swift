# -*- coding: utf-8 -*-
# !/usr/bin/env python

import asyncio
import hashlib
import inspect
import time
from datetime import datetime, timedelta

import aiohttp

from .logger import get_logger

LOGGER = get_logger(name=__name__)


class AsyncProxyClient(object):
    def __init__(self, secret_key, partner_id, server_id=None):
        if not (isinstance(secret_key, str) and secret_key):
            raise Exception('Please provide valid secret_key')
        if not (isinstance(partner_id, str) and partner_id):
            raise Exception('Please provide valid partner_id')
        if not (server_id is None or server_id == '' or (isinstance(server_id, int) and server_id > 0)):
            raise Exception('Please provide valid server_id')

        self.secret_key = secret_key
        self.partner_id = partner_id
        self.server_id = server_id or ''

        self.host = 'https://api.proxyswift.com:88'
        self.url_get_ip = self.host + '/ip/get'
        self.url_get_task = self.host + '/task/get'
        self.url_change_ip = self.host + '/ip/change'

    async def get_ip(self, interface_id=None, pool_id=3):
        i = 1
        while True:
            result = await self._request(
                url=self.url_get_ip,
                data={
                    'server_id': self.server_id,
                    'pool_id': pool_id,
                    'interface_id': interface_id or '',
                }
            )
            if result['code'] == 200:
                result = result['data']
                if interface_id:
                    result = (result or [{}])[0]
                return result
            else:
                self._log('error', inspect.currentframe().f_code.co_name, result)

            await asyncio.sleep(i % 2 + 1)
            i += 1

    async def change_ip(self, interface_id, pool_id=3, _filter=24):
        task_id = await self._change_ip(interface_id=interface_id, _filter=_filter)

        i = 1
        while True:
            await asyncio.sleep(i % 2 + 1)

            if not await self._get_task(task_id=task_id):
                task_id = await self._change_ip(interface_id=interface_id, _filter=_filter)
                continue

            i += 1

            return await self.get_ip(pool_id=pool_id, interface_id=interface_id)

    async def _change_ip(self, interface_id, _filter):
        i = 1
        while True:
            result = await self._request(
                url=self.url_change_ip,
                data={
                    'server_id': self.server_id,
                    'interface_id': interface_id,
                    'filter': _filter,
                }
            )

            task_id = result['data'].get('task_id')
            if result['code'] == 202 and task_id:
                return task_id
            else:
                self._log('error', inspect.currentframe().f_code.co_name, result)

            await asyncio.sleep(i % 2 + 1)
            i += 1

    async def _get_task(self, task_id, timeout=300):
        end = datetime.now() + timedelta(seconds=timeout)

        i = 1
        while datetime.now() <= end:
            result = await self._request(
                url=self.url_get_task,
                data={'task_id': task_id}
            )

            status = result['data']['status']
            if result['code'] == 200:
                if status == 'success':
                    return True
                elif status == 'failed':
                    self._log('error', inspect.currentframe().f_code.co_name, result)
                    return False
                else:
                    self._log('warning', inspect.currentframe().f_code.co_name, result)
            else:
                self._log('error', inspect.currentframe().f_code.co_name, result)

            await asyncio.sleep(i % 2 + 1)
            i += 1

        self._log('error', inspect.currentframe().f_code.co_name, f'timeout after {timeout} seconds')
        return False

    async def _request(self, url, data):
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            while True:
                try:
                    source_data = self._prepare(data=data)
                    async with session.get(url, params=source_data, timeout=15) as resp:
                        return await resp.json()
                except Exception as e:
                    self._log('exception', inspect.currentframe().f_code.co_name, e)
                    await asyncio.sleep(3)

    def _prepare(self, data):
        source_data = {
            'partner_id': self.partner_id,
            'timestamp': int(time.time())
        }

        source_data.update(data)

        sign = ''.join([
            '{}{}'.format(*i)
            for i in sorted(
                [i for i in source_data.items()],
                key=lambda i: i[0]
            )
        ])

        md_5 = hashlib.md5()
        md_5.update((sign + self.secret_key).encode('utf-8'))
        sign = md_5.hexdigest()
        source_data.update({'sign': sign})

        return source_data

    def _log(self, level, method_name, message):
        return getattr(LOGGER, level)(f'{self.__class__.__name__}.{method_name}: {message}')
