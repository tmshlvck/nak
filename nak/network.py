#!/usr/bin/env python3
# coding: utf-8

"""
nak.network

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

import yaml
from collections import OrderedDict
import logging
import os.path

import nak


class NAKConf(object):
  def __init__(self, yamlfilename=None):
    if yamlfilename:
      self.yamlfilename = yamlfilename
      self.load(self.yamlfilename)
    else:
      self.confstruct = OrderedDict()

  def load(self, yamlfilename=None):
    if not yamlfilename:
      yamlfilename = self.yamlfilename
    with open(yamlfilename, 'r') as fh:
      self.confstruct = yaml.load(fh, Loader=yaml.Loader)

  def dump(self):
    return yaml.dump(self.confstruct, Dumper=yaml.Dumper)

  def save(self, yamlfilename=None):
    if not yamlfilename:
      yamlfilename = self.yamlfilename
    with open(yamlfilename, 'w') as fh:
      fh.write(self.dump())


class Switch(NAKConf):
  def setVLANs(self, vlans):
    self.confstruct['vlans'] = vlans

  def mergeVLANs(self, vlans):
    self.confstruct['vlans'] = {**self.confstruct.get('vlans',{}), **vlans}


class Network(NAKConf):
  """ Prototype config:
---
name: Ignum
switch_confdir: /var/lib/nak/yconfig
vlans:
  global:
    9:
      name: Mgmt-Oldnet-PDU-IPMI
    10:
      name: IPMI
    11:
      name: netmgmt
    12:
      name: PVE-A
  customer1:
    9:
      name: Mgmt-Oldnet-PDU-IPMI
    13:
      name: Customer-Local
      
switch:
  - hostname: itchy.net.ignum.cz
    config: /var/lib/nak/yconfig/itchy.net.ignum.cz.yml
    core: true
    vlan_group: global
    
  """

  def getSwitchConfig(self, netswitch):
    if 'config' in netswitch:
      return Switch(netswitch['config'])
    else:
      return Switch(os.path.join(self.confstruct['switch_confdir'],'%s.yml' % netswitch['hostname']))

  def getSwitches(self):
    for s in self.confstruct['switch']:
      yield (s, self.getSwitchConfig(s))

  @classmethod
  def structDiff(cls, old, new):
    if old == new:
      return "subtree is equal"
    else:
      if not old and new:
        return "old: missing, new: %s" % str(new)
      elif old and not new:
        return "old: %s , new: missing" % str(old)
      elif isinstance(old, dict) and isinstance(new, dict):
        res = ""
        for k in old:
          if k in new:
            if old[k] == new[k]:
              pass
            else:
              res += "%s->%s\n" % (k, cls.structDiff(old[k], new[k]))
          else:
            res += "%s-> old: %s, new missing\n" % (k, str(old[k]))
        for k in new:
          if k in old:
            pass
          else:
            res += "%s-> old missing, new: %s\n" % (k, str(new[k]))
        return res
      elif isinstance(old, list) and isinstance(new, list):
        res = ""
        for e in old:
          if e in new:
            pass
          else:
            res += "- old: %s, new missing\n" % str(e)
        for k in new:
          if k in old:
            pass
          else:
            res += "- old missing, new: %s\n" % str(e)
        return res
      else:
        return "old: %s, new: %s" % (str(old), str(new))

  def updateVLANs(self, sim=False):
    for swdef, sw in self.getSwitches():
      if 'vlan_group' in swdef:
        new_vlans = self.confstruct['vlans'][swdef['vlan_group']]
        if sim or swdef.get('readonly', False):
          logging.info("Simulating setting VLANs for host %s", swdef['hostname'])
          logging.info(self.structDiff(sw.confstruct['vlans'], new_vlans))
        else:
          logging.debug("Setting VLANs for host %s", swdef['hostname'])
          sw.confstruct['vlans'] = new_vlans
          sw.save()


  def update(self, sim=False):
    self.updateVLANs(sim)

