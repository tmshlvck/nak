#!/usr/bin/env python3

import json
from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager
import sys
import os.path
import yaml


class AnsibleInventory(object):
  def __init__(self):
    pass


  @classmethod
  def get_hosts(cls, sources=None, vault_pass=None, limit=None):
    """
    sources: ['hosts',]
    vault_pass: str
    """

    loader = DataLoader()
    if vault_pass:
      loader.set_vault_password(vault_pass)
    if sources:
      inventory = InventoryManager(loader=loader, sources=sources)
    else:
      inventory = InventoryManager(loader=loader)

    variable_manager = VariableManager(loader=loader, inventory=inventory)

    hosts = variable_manager.get_vars()['groups']['all']

    for h in hosts:
      hv = variable_manager.get_vars(host=inventory.get_host(h))
      if not limit or hv['inventory_hostname'] in limit or hv['inventory_hostname_short'] in limit:
        yield {k:(hv[k] if k in hv else None) for k in ['ansible_user', 'ansible_password', 'ansible_become_password', 'inventory_hostname', 'inventory_hostname_short', 'group_names']}


  @classmethod
  def get_type(cls, group_names):
    if 'ios' in group_names:
      return 'ios'

    if 'nxos' in group_names:
      return 'nxos'

    if 'dellos10' in group_names:
      return 'dellos10'

    raise Exception('Can not derive type from: %s' % str(group_names))


class BatchConfig(object):
  def __init__(self, filename):
    with open(filename, 'r') as fh:
      self.cfg = yaml.safe_load(fh)



