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
        'napalm-dellos10',
        'click',
        'jinja2',
        'ansible',
        ],
    packages = ['nak', ],
    package_data = {'nak': ['templates/ios.j2','templates/dellos10.j2'],},
    scripts = [
        'scripts/batch',
        'scripts/box',
        'scripts/yaml2box',
        'scripts/box2yaml',
        'scripts/inv2oxidized'
        ],
   )

