# -*- coding: utf-8 -*-
# !/usr/bin/env python

import hashlib
import inspect
import json
import logging
import time

import requests

logger = logging.getLogger(__name__)
requests.packages.urllib3.disable_warnings()


class ProxySwift(object):
    def __init__(self, server_id=2, secret_key='Kg6t55fc39FQRJuh92BwZBMXyK3sWFkJ', partner_id='2017072514450843'):
        self.server_id = server_id
        self.secret_key = secret_key
        self.partner_id = partner_id

        self.host = 'https://api.proxyswift.com'
        self.url_get_ip = self.host + '/ip/get'
        self.url_get_task = self.host + '/task/get'
        self.url_change_ip = self.host + '/ip/change'

    def get_ip(self, interface_id=None, pool_id=1):
        i = 1
        while True:
            result = self._requests_get(
                url=self.url_get_ip,
                data={
                    'server_id': self.server_id,
                    'pool_id': pool_id,
                    'interface_id': interface_id or '',
                }
            )
            if result['code'] == 200:
                return result['data']
            else:
                self._log('error', inspect.currentframe().f_code.co_name, result)
                time.sleep(i % 2 + 1)

    def change_ip(self, interface_id, pool_id=1, _filter=24):
        task_id = self._change_ip(interface_id=interface_id, _filter=_filter)

        i = 1
        while True:
            time.sleep(i % 2 + 1)

            if not self._get_task(task_id=task_id):
                task_id = self._change_ip(interface_id=interface_id, _filter=_filter)
                continue

            return self.get_ip(pool_id=pool_id, interface_id=interface_id)[0]

    def _change_ip(self, interface_id, _filter):
        i = 1
        while True:
            result = self._requests_get(
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
                time.sleep(i % 2 + 1)

    def _get_task(self, task_id):
        i = 1
        while True:
            result = self._requests_get(
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
                time.sleep(i % 2 + 1)

    def _requests_get(self, url, data):
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

        return requests.get(url, params=source_data, verify=False, json=True).json()

    def _log(self, level, method_name, message):
        return getattr(logger, level)(f'{self.__class__.__name__}.{method_name}: {message}')


if __name__ == '__main__':
    _proxy_swift = ProxySwift()

    _data = _proxy_swift.get_ip(pool_id=1)  # 获取1号池所有ip
    print(json.dumps(obj=_data, indent='\t', ensure_ascii=False))

    _data = _proxy_swift.change_ip(interface_id=23)  # 更换23号ip
    print(json.dumps(obj=_data, indent='\t', ensure_ascii=False))
