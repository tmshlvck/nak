#!/usr/bin/env python

from setuptools import setup

setup(name='nak',
    version='1.0',
    description='Network Administration Kit',
    install_requires = [
        'wheel',
        'netmiko',
        'ciscoconfparse',
        'napalm',
        'napalm-procurve',
#        'napalm-dellos10',
        'click',
        'jinja2',
        'ansible',
        ],
    packages = ['nak', ],
    scripts = [
        'scripts/nak',
        'scripts/box2yaml',
        'scripts/inv2csv',
        'scripts/netgen'
        ],
   )

