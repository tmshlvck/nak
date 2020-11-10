#!/usr/bin/env python3
# coding: utf-8

"""
nak.inventory

Copyright (C) 2020 Tomas Hlavacek (tmshlvck@gmail.com)

This module is a part of Network Automation Toolkit.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
"""

from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager
import os.path
import yaml
from collections import OrderedDict
import logging

import nak

class AnsibleInventory(object):
  def __init__(self, sources=['/etc/inventory/hosts',], vault_pass=None):
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
      accept_vars = ['ansible_user', 'ansible_password', 'ansible_become_password', 'inventory_hostname', 'inventory_hostname_short', 'group_names', 'nak_confdir']
      return {k:(hostvars[k] if k in hostvars else None) for k in accept_vars}

    hosts = self.variable_manager.get_vars()['groups']['all']

    for h in hosts:
      hv = self.variable_manager.get_vars(host=self.inventory.get_host(h))
      if not limit or hv['inventory_hostname'] in limit or hv['inventory_hostname_short'] in limit:
        #logging.debug("Skipping %s due to limit." % h['inventory_hostname'])
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
    elif 'linux' in group_names:
      return 'linux'
    else:
      raise Exception('Can not derive type from: %s' % str(group_names))


  def getHosts(self, limit=None):
    """
    limit: ['host1', 'host2', ...]
    """
    for h in self.getHostsRaw(limit):
      try:
        h['boxtype'] = self.getType(h)
        yield h
      except:
        pass



class AnsibleInventoryConfigs(AnsibleInventory):
  WRITE_TYPES = ['ios', 'nxos', 'dellos10']

  @classmethod
  def mergeConfigs(cls, cfgs):
    """
      cfgs = [cfg1, cfg2, ...]
    """
    if len(cfgs) == 1:
      return cfgs[0]
    else:
      res = OrderedDict()
      for c in cfgs:
        for k in c:
          res[k] = c[k]
      return res


  @classmethod
  def isTypeSupported(cls, t):
    if t in cls.WRITE_TYPES:
      return True

    return False


  def getHostsWithConfPaths(self, limit=None):
    for h in self.getHosts(limit):
      if not self.isTypeSupported(h['boxtype']):
        logging.debug('Skipping unsupported host %s', h['inventory_hostname'])
        continue

      confdir = ''

      if 'nak_confdir' in h and h['nak_confdir']:
        confdir = h['nak_confdir']
      hcp = os.path.join(confdir, '%s.yml' % h['inventory_hostname_short'])
      if not os.path.exists(hcp):
        hcp = os.path.join(confdir, '%s.yml' % h['inventory_hostname'])

      yield (h, hcp) # (dict hostdef, hostConfPath)


  def loadConfStructRecursive(self, cfgfilename):
    with open(ccp, 'r') as fh:
      cc = yaml.load(fh, Loader=yaml.Loader)

      inhcfg = {}
      if 'inherit' in cc and cc['inherit']:
        for i in cc['inherit']:
          ic = self.loadConfStructRecursive(i)
          inhcfg = self.mergeConfigs([inhcfg, ic])

      return self.mergeConfigs([inhcfg, cc])



  def getHostsWithConfStruct(self, limit=None):
    for h,hcp in self.getHostsWithConfPaths(limit):
      if not hc:
        raise Exception("Missing config file %s for host %s", hcp, str(h))

      yield (h, self.loadConfStructRecursive(hc))


