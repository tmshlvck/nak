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
- name: Ignum
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
  def structDiff(cls, a, b):
    if a == b:
      return "Diff: A==B"
    else:
      return "A: %s\nB: %s" % (str(a), str(b))

  def updateVLANs(self, sim=False):
    for swdef, sw in self.getSwitches():
      if 'vlan_group' in swdef:
        new_vlans = self.confstruct['vlans'][swdef['vlan_group']]
        if sim:
          logging.info("Simulating setting VLANs for host %s", swdef['hostname'])
          logging.info(self.structDiff(sw.confstruct['vlans'], new_vlans))
        else:
          logging.debug("Setting VLANs for host %s", swdef['hostname'])
          sw.confstruct['vlans'] = new_vlans
          sw.save()


  def update(self, sim=False):
    self.updateVLANs(sim)

