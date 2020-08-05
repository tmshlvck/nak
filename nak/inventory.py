#!/usr/bin/env python3

from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager


class AnsibleInventory(object):
  def __init__(self, sources, vault_pass):
    """
    sources: ['directory/hosts',]
    vault_pass: str
    """

    self.loader = DataLoader()
    if vault_pass:
      self.loader.set_vault_password(vault_pass)
    if sources:
      self.inventory = InventoryManager(loader=self.loader, sources=self.sources)
    else:
      self.inventory = InventoryManager(loader=self.loader)

    self.variable_manager = VariableManager(loader=self.loader, inventory=self.inventory)


  def getHostsiRaw(self, limit=None):
    """
    limit: ['host1', 'host2', ...]
    """

    hosts = self.variable_manager.get_vars()['groups']['all']

    for h in hosts:
      hv = self.variable_manager.get_vars(host=inventory.get_host(h))
      if not limit or hv['inventory_hostname'] in limit or hv['inventory_hostname_short'] in limit:
        yield {k:(hv[k] if k in hv else None) for k in ['ansible_user', 'ansible_password', 'ansible_become_password', 'inventory_hostname', 'inventory_hostname_short', 'group_names']}


  @classmethod
  def _getType(cls, group_names):
    if 'ios' in group_names:
      return 'ios'

    elif 'nxos' in group_names:
      return 'nxos'

    elif 'os10' in group_names or 'dellos10' in group_names:
      return 'os10'

    elif 'procurve' in group_names:
      return 'procurve'

    elif 'ironware' in group_names:
      return 'ironware'

    elif 'junos' in group_names:
      return 'junos'

    else:
      raise Exception('Can not derive type from: %s' % str(group_names))


  def getHosts(self, limit=None):
    """
    limit: ['host1', 'host2', ...]
    """
    for h in self.getHostsRaw():
      try:
        h['model'] = self._getType(h['group_names'])
      except:
        h['model'] = 'Unknown'

      yield h



