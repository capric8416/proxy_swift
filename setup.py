#!/usr/bin/env python
# -*- coding: utf-8 -*-

import ast
from setuptools import setup, find_packages


requirements = [
    'requests>=2.18.3',
]

setup(
    name='proxy_swift',
    version='1.0',
    description="A Python Package for ProxySwift",
    long_description='',
    author="liuchang, capric",
    author_email='764191074@qq.com, capric8416@gmail.com',
    url='https://github.com/6148cirpac/proxy_swift',
    packages=find_packages(),
    package_dir={},
    entry_points={},
    include_package_data=True,
    install_requires=requirements,
    license="LGPL license",
    zip_safe=False,
    keywords='proxy_swift',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: LGPL License',
        'Natural Language :: English, Chinese',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
)
