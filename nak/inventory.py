#!/usr/bin/env python3

from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager


class AnsibleInventory(object):
  def __init__(self, sources, vault_pass=None):
    """
    sources: ['directory/hosts',]
    vault_pass: str
    """

    self.loader = DataLoader()
    if vault_pass:
      self.loader.set_vault_password(vault_pass)
    if sources:
      self.inventory = InventoryManager(loader=self.loader, sources=sources)
    else:
      self.inventory = InventoryManager(loader=self.loader)

    self.variable_manager = VariableManager(loader=self.loader, inventory=self.inventory)


  def getHostsRaw(self, limit=None):
    """
    limit: ['host1', 'host2', ...]
    """

    def filter_vars(hostvars):
      filter_vars = ['ansible_user', 'ansible_password', 'ansible_become_password', 'inventory_hostname', 'inventory_hostname_short', 'group_names', 'nak_confdir', 'nak_commonconf']}
      return {k:(hostvars[k] if k in hostvars else None) for k in filter_vars}

    hosts = self.variable_manager.get_vars()['groups']['all']

    for h in hosts:
      hv = self.variable_manager.get_vars(host=self.inventory.get_host(h))
      if not limit or hv['inventory_hostname'] in limit or hv['inventory_hostname_short'] in limit:
        yield filter_vars(hv)


  @classmethod
  def getType(cls, hostdef):
    if not 'group_names' in hostdef:
      raise Exception("Missing group_names struct in host definition.")

    group_names = hostdef['group_names']
    if 'ios' in group_names:
      return 'ios'
    elif 'nxos' in group_names:
      return 'nxos'
    elif 'dellos10' in group_names:
      return 'dellos10'
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
        h['boxtype'] = self.getType(h)
        yield h
      except:
        pass



class AnsibleInventoryConfig(AnsibleInventory):
  WRITE_TYPES = ['ios', 'nxos', 'dellos10']

  @classmethod
  def mergeConfigs(cls, cfgs):
    """
      cfgs = [cfg1, cfg2, ...]
    """
    res = OrderedDictt()
    for c in cfgs:
      for k in c:
        res[k] = c[k]
    return res


  @classmethod
  def isTypeSupported(cls, t):
    if t in cls.WRITE_TYPES:
      return True

    return False


  def getHostsWithConfPaths(self):
    for h in self.getHosts():
      if not self.isTypeSupported(h['boxtype']):
        nak.d('Skipping unsupported host %s' % h['inventory_hostname'])
        continue

      if 'nak_commonconf' in h and h['nak_commonconf']:
        ccp = h['nak_commonconf']
      else:
        ccp = None

      confdir = ''
      if 'nak_confdir' in h and h['nak_confdir']:
        confdir = h['nak_confdir']
      hcp = os.path.join(confdir, '%s.yml' % h['inventory_hostname_short']

      yield (h, ccp, hcp) # (dict hostdef, str commonConfPath, hostConfPath)


  def getHostsWithConfStruct(self):
    for h,ccp,hcp in self.getHostsWithConfPaths(self):
      cc = {}
      if ccp:
        with open(ccp, 'r') as fh:
          cc = yaml.load(fh, Loader=yaml.Loader)

      with open(os.path.join(hcp, 'r') as fh:
        hc = yaml.load(fh, Loader=yaml.Loader)

      yield (h, self.mergeConfigs([cc, hc]))


