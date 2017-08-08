# -*- coding: utf-8 -*-
# !/usr/bin/env python

import hashlib
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

    def get_ip(self, pool_id=1, interface_id=None):
        return self._requests_get(
            url=self.url_get_ip,
            data={
                'server_id': self.server_id,
                'pool_id': pool_id,
                'interface_id': interface_id or '',
            }
        )

    def change_ip(self, interface_id, _filter=24):
        task_id = self._requests_get(
            url=self.url_change_ip,
            data={
                'server_id': self.server_id,
                'interface_id': interface_id,
                'filter': _filter,
            }
        )['taskId']

        i = 1
        while True:
            time.sleep(i % 2 + 1)

            data = self._get_task(task_id)
            if data['status'] != 'success':
                logger.error(data)
                continue

            ip_port = self.get_ip(interface_id=interface_id)
            return ip_port[0]

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

    def _get_task(self, task_id):
        return self._requests_get(
            url=self.url_get_task,
            data={'task_id': task_id}
        )


if __name__ == '__main__':
    _proxy_swift = ProxySwift()

    _data = _proxy_swift.get_ip(pool_id=1)  # 获取1号池所有ip
    print(json.dumps(obj=_data, indent='\t', ensure_ascii=False))

    _proxy_swift.change_ip(interface_id=34)  # 更换ip
    _data = _proxy_swift.get_ip(pool_id=1, interface_id=34)
    print(json.dumps(obj=_data, indent='\t', ensure_ascii=False))
