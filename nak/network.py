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

  def setTrunkVLANs(self, iface, untagged, tagged):
    self.confstruct['ports'][iface]['untagged'] = untagged
    self.confstruct['ports'][iface]['tagged'] = tagged

  def setPortMTU(self, iface, mtu):
    self.confstruct['ports'][iface]['mtu'] = int(mtu)

  def getActiveVLANs(self, ignore_ifaces=set()):
    vlans = set()
    for iface in self.confstruct['ports']:
      if iface in ignore_ifaces:
        continue
      ifdef = self.confstruct['ports'][iface]
      if ifdef.get('shutdown', False):
        continue
      if ifdef.get('clean', False):
        continue
      if ifdef.get('type', 'access') == 'access':
        vlans.add(int(ifdef.get('untagged', 1)))
      elif ifdef['type'] == 'trunk':
        if 'untagged' in ifdef:
          vlans.add(int(ifdef['untagged']))
        vlans |= set([int(vid) for vid in ifdef.get('tagged', [])])

    for v in vlans:
      if not v in self.confstruct['vlans']:
        raise Exception('switch %s has active undefined VLAN %d' % (self.confstruct['hostname'],v))
    return sorted(list(vlans))


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
      
switches:
  gloria.net.ignum.cz:
    core: true
    vlan_group: global
    backbone:
      - interface: port-channel1
        peer: itchy.net.ignum.cz
        peer_interface: port-channel1
      - interface: port-channel1
        peer: scratchy.net.ignum.cz
        peer_interface: port-channel1
  a7.net.ignum.cz:
    readonly: true
    core: false
    vlan_group: global
    uplinks:
      - interface: '48'
        peer: burns.net.ignum.cz
        peer_interface: GigabitEthernet0/36
        minimize: true 
  """

  def getSwitchConfig(self, switchname):
    swdef = self.confstruct['switches'][switchname]
    if 'config' in swdef:
      return Switch(swdef['config'])
    else:
      return Switch(os.path.join(self.confstruct['switch_confdir'],'%s.yml' % switchname))

  def getSwitchesWithConf(self):
    for switchname in self.confstruct['switches']:
      yield (switchname, self.confstruct['switches'][switchname], self.getSwitchConfig(switchname))

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
    for swname, swdef, swconf in self.getSwitchesWithConf():
      if 'vlan_group' in swdef:
        # if not swdef.get('core', False): then minimize - TODO
        new_vlans = self.confstruct['vlans'][swdef['vlan_group']]
        if sim or swdef.get('readonly', False):
          logging.info("Simulating setting VLANs for host %s", swname)
          logging.info(self.structDiff(swconf.confstruct['vlans'], new_vlans))
        else:
          logging.debug("Setting VLANs for host %s", swname)
          swconf.confstruct['vlans'] = new_vlans
          swconf.save()


  def updateL2Backbone(self, sim=False):
    mtu = self.confstruct.get('backbone', {}).get('mtu', 1500)

    for swname, swdef, swconf in self.getSwitchesWithConf():
      try:
        if swdef.get('core', False):
          for bl in swdef.get('backbone', []):
            if sim or swdef.get('readonly', False):
              logging.info("Simulating setting backbone trunk for host %s port %s", swname, bl['interface'])
            else:
              logging.debug("Setting backbone trunk for host %s port %s", swname, bl['interface'])
              swconf.setTrunkVLANs(bl['interface'], 1, 'all')
              swconf.setPortMTU(bl['interface'], mtu)
          
        else: # access
          for ul in swdef.get('uplinks', []):
            if ul.get('minimize', False):
              vlans = swconf.getActiveVLANs(set([u['interface'] for u in swdef['uplinks']]))
            else:
              vlans = 'all'

            if sim or swdef.get('readonly', False):
              logging.info("Simulating setting uplink trunk on host %s port %s", swname, ul['interface'])
            else:
              logging.debug("Setting uplink trunk on host %s port %s", swname, ul['interface'])
              swconf.setTrunkVLANs(ul['interface'], 1, vlans)
              swconf.setPortMTU(ul['interface'], mtu)

            peerconf = self.getSwitchConfig(ul['peer'])
            if sim or peerconf.confstruct.get('readonly', False):
              logging.info("Simulating setting downlink trunk on host %s port %s towards %s", ul['peer'], ul['peer_interface'], swname)
            else:
              logging.info("Setting downlink trunk on host %s port %s towards %s", ul['peer'], ul['peer_interface'], swname)
              peerconf.setTrunkVLANs(ul['peer_interface'], 1, vlans)
              peerconf.setPortMTU(ul['peer_interface'], mtu)
              peerconf.save()
            peerconf.save()
        swconf.save()
      except:
        logging.error("Error in YAML configuration modify on %s", swname)
        raise


  def update(self, sim=False):
    self.updateVLANs(sim)
    self.updateL2Backbone(sim)
