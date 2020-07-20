#!/usr/bin/env python

from setuptools import setup

setup(name='nak',
    version='1.0',
    description='Network Administration Kit',
    install_requires = [
        'netmiko',
        'ciscoconfparse',
        'napalm',
        'napalm-procurve',
        'napalm-dellos10',
        'click',
        'jinja2',
        'ansible',
        ],
    packages = ['nak', ],
    scripts = [
        'box.py',
        'batchbox.py',
        'conf2yaml.py'
        ],
   )

