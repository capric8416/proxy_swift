# -*- coding: utf-8 -*-
# !/usr/bin/env python


import json
from multiprocessing.dummy import Pool as ThreadPool

from proxy_swift import ProxySwift


def get_one_ip(handler, pool_id, interface_id):
    result = handler.get_ip(pool_id=pool_id, interface_id=interface_id)
    print(json.dumps(obj=result, indent='\t', ensure_ascii=False))
    return result


def get_all_ip(handler, pool_id):
    result = handler.get_ip(pool_id=pool_id)
    print(json.dumps(obj=result, indent='\t', ensure_ascii=False))
    return result


def change_one_ip(handler, pool_id, interface_id):
    result = handler.change_ip(pool_id=pool_id, interface_id=interface_id)
    print(json.dumps(obj=result, indent='\t', ensure_ascii=False))
    return result


def change_all_ip(handler, data):
    def _change(item):
        result = handler.change_ip(interface_id=item['id'])
        print(json.dumps(obj=result, indent='\t', ensure_ascii=False))

    pool = ThreadPool(len(data))
    pool.map(_change, data)
    pool.close()
    pool.join()


if __name__ == '__main__':
    # server_id, secret_key, partner_id参数请修改为自己的
    _proxy_swift = ProxySwift(server_id=0, secret_key='', partner_id='')

    # 获取1号池23号ip
    _data = get_one_ip(handler=_proxy_swift, pool_id=1, interface_id=23)

    # 获取1号池所有ip
    _data = get_all_ip(handler=_proxy_swift, pool_id=1)

    # 更换1号池23号ip
    change_one_ip(handler=_proxy_swift, pool_id=1, interface_id=23)

    # 更换1号池所有ip
    change_all_ip(handler=_proxy_swift, data=_data)
