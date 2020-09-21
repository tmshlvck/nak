#!/usr/bin/env python3
# coding: utf-8

"""
nak.os10

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


import ciscoconfparse
import re
from collections import OrderedDict,defaultdict
import logging

import nak
import nak.cisco



class OS10Parser(nak.cisco.CiscoLikeParser):
  def __init__(self, config):
    self.cfg = OrderedDict()
    self.parseConfig(config)


  @classmethod
  def _iface_filter(cls, ifname, iface):
    if 'mgmt' in ifname or 'management' in ifname:
      return False

    if 'vlan' in ifname:
      return False

    return True
  

  @classmethod
  def _parse_ifaces(cls, cp, active_vlans):
    ifaces = OrderedDict()

    for o in cp.find_objects(r"^\s*interface"):
      name = o.re_match_typed(r"^\s*interface\s+(.+)$").strip()
      if not name:
        raise Exception("Wrong interface: %s" % str(o))

      if 'breakout' in name:
        continue

      if not name in ifaces:
        ifaces[name] = OrderedDict()
        ifaces[name]['shutdown'] = False

      for c in o.children:
        m = c.re_match_typed(r"^\s*description\s+(.+)$").strip()
        if m:
          ifaces[name]['descr'] = m
          continue

        m = c.re_match_typed(r"^\s*(shutdown)\s*$")
        if m:
          ifaces[name]['shutdown'] = True
          continue

        m = c.re_match_typed(r"^\s*switchport mode\s+(.+)$")
        if m:
          ifaces[name]['type'] = m
          continue

        m = c.re_match_typed(r"^\s*switchport access vlan\s+([0-9]+)\s*$")
        if m:
          ifaces[name]['access_vlan'] = int(m)
          continue

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] = cls._normalize_vlan_list(m)
          continue

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan add\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] += self._normalize_vlan_list(m)
          continue

        m = c.re_match_typed(r'^\s*(no\s+switchport)\s*$')
        if m:
          ifaces[name]['type'] = 'no switchport'

        m = c.re_match_typed(r'^\s*channel-group\s+(.+)')
        if m:
          mi = re.match(r'^\s*([0-9]+)\s+mode\s+(\S.+)$', m)
          if mi:
            ifaces[name]['lag'] = int(mi.group(1))
            ifaces[name]['lagmode'] = mi.group(2).strip()
          else:
            ifaces[name]['lag'] = int(m)
            ifaces[name]['lagmode'] = 'on'
 
        m = c.re_match_typed(r'^\s*vlt-port-channel\s+(.*)\s*$')
        if m:
          ifaces[name]['mlag'] = int(m)

        m = c.re_match_typed(r'^\s*mtu\s+([0-9]+)\s*$')
        if m:
          ifaces[name]['mtu'] = int(m)-22 # OS10 has WEIRD MTU computation - they count the Eth header including 802.1Q tag and the CRC trailer, all sums up to 22 bytes more than what Cisco/others call MTUa (= L3 datagram size)
        
        logging.debug("Ignored: %s", c.text)

    to_remove = []
    for ifname in ifaces:
      i = ifaces[ifname]
      if not 'type' in i:
        i['type'] = 'access'
      i['untagged'] = (i['access_vlan'] if 'access_vlan' in i else 1)
      if 'allowed_vlan' in i:
        utg = ({i['untagged']} if 'untagged' in i else set())
        i['tagged'] = sorted(list(set(i['allowed_vlan']) - utg))

      i.pop('access_vlan', None)
      i.pop('allowed_vlan', None)

      if 'lag' in i:
        i.pop('untagged', None)
        i.pop('tagged', None)

      if not cls._iface_filter(ifname, i):
        to_remove.append(ifname)

      if i['type'] == 'access' and i['untagged'] == 1 and not 'lag' in i and not 'descr' in i and i['shutdown']:
        ifaces[ifname] = OrderedDict()
        ifaces[ifname]['clean'] = True
        continue

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces

  @classmethod
  def _parse_vlans(cls, cp):
    vlans = OrderedDict()
 
    for o in cp.find_objects(r"^\s*interface"):
      vids = o.re_match_typed(r"^\s*interface vlan([0-9]+)\s*$").strip()
      if vids:
        vid = int(vids)

        if not vid in vlans:
          vlans[vid] = OrderedDict()

        for c in o.children:
          m = c.re_match_typed(r"^\s*description\s+(.+)$", result_type=str)
          if m:
            vlans[vid]['name'] = m
            continue
        
        logging.debug("Ignored: %s", c.text)

    return vlans


  def parseConfig(self, config):
    cp = ciscoconfparse.CiscoConfParse(config)

    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))
    if not o:
      raise ValueError("Can not parse config without hostname")
    hostname = o[0].re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    self.cfg['hostname'] = hostname

    vlans = self._parse_vlans(cp)
    self.cfg['vlans'] = vlans
    self.cfg['ports'] = self._parse_ifaces(cp, vlans)
    self.cfg['users'] = self._parse_users(cp)





class OS10Box(nak.BasicGen,nak.Box):
  IGNORE_VLANS = [1,]

  def __init__(self):
    super().__init__("dellos10")

  def genSyncVLANS(self, newconf, activeconf):
    for vid in set(activeconf['vlans'])-set(newconf['vlans']):
      if not vid in self.IGNORE_VLANS:
        yield "no interface vlan%d" % vid

    for vid in newconf['vlans']:
      if not vid in self.IGNORE_VLANS:
        yield "interface vlan%d" % vid
        if 'name' in newconf['vlans'][vid]:
          yield " description %s" % self._normalize_namestr(newconf['vlans'][vid]['name'])
        yield '!'

  def genSyncPhysPorts(self, newconf, activeconf, pattern="ethernet"):
    def _expand_tagged_vlans(conf, p):
      if not p in conf['ports']:
        return None

      pd = conf['ports'][p]
      if 'tagged' in pd:
        if not pd['tagged']:
          return None

        if type(pd['tagged']) is str:
          if (pd['tagged'].lower() == 'all' or pd['tagged'] == '*'):
              return conf['vlans'].keys()
          else:
            raise ValueError('Unsupported tagged value:' % tgt)
        else:
          if 'untagged' in pd:
            try:
              pd['tagged'] = list((set(pd['tagged']) - {pd['untagged'],}))
            except:
              print('DEBUG: Exception in %s %s'%(str(p),str(pd)))
              raise
          return list(self._compact_int_list(pd['tagged']))
      else:
        return None


    for p in newconf['ports']:
      pd = newconf['ports'][p]

      if not pattern in p:
        continue

      if not type(pd) is dict:
        logging.debug("Skipping port with not config %s", p)
        continue

      if 'clean' in pd and pd['clean'] == True:
        yield "default interface %s" % p
        yield "interface %s" % p
        yield " shutdown"
        yield "!"
        continue

      yield "interface %s " % p
      if 'descr' in pd and pd['descr']:
        yield " description %s" % pd['descr']

      if 'shutdown' in pd and pd['shutdown']:
        yield " shutdown"
      else:
        " no shutdown"

      if 'lag' in pd:
        pcn = 'port-channel%d' % pd['lag']
        if pcn in newconf['ports']:
          pd['type'] = newconf['ports'][pcn]['type']
          pd['tagged'] = newconf['ports'][pcn]['tagged']
          pd['untagged'] = newconf['ports'][pcn]['untagged']

      if 'type' in pd:
        if pd['type'] == 'access':
          yield " switchport mode access"
          yield " switchport access vlan %d" % pd['untagged']
        elif pd['type'] == 'trunk':
          yield " switchport mode trunk"
 
          if 'untagged' in p:
            yield " switchport access vlan %d" % pd['untagged']

          tgt = _expand_tagged_vlans(newconf, p)
          acttagged = _expand_tagged_vlans(activeconf, p)

          if tgt:
            if tgt != acttagged:
              yield " no switchport trunk allowed vlan"
              yield " switchport trunk allowed vlan %s" % ",".join([str(v) for v in tgt])
          else:
            yield " no switchport trunk allowed vlan"

        elif pd['type'] == 'no switchport':
          pass
        else:
          raise ValueError("Unknown port %s type: %s" % (p, pd['type']))
      else:
        pass

      if 'mtu' in pd:
        yield " mtu %d" % (pd['mtu']+22) # OS10 means by MTU the total Ethernet frame size, not IP MTU, we add 22 (14 for EthII, 4 for dot1q and 4 for CRC)

      if 'mlag' in pd:
        yield " vlt-port-channel %s" % str(pd['mlag'])

      if 'lag' in pd:
        yield " channel-group %d mode %s" % (pd['lag'], (pd['lagmode'] if 'lagmode' in pd else "on"))

      if 'extra' in pd:
        for e in pd['extra']:
          yield "%s" % e

      yield "!"


  def genSyncPortChannels(self, newconf, activeconf):
    for p in newconf['ports']:
      pd = newconf['ports'][p]

      if pd and type(pd) is dict:
        if 'clean' in pd and pd['clean'] and 'port-channel' in p.lower():
          yield "no interface %s" % p

    for p in activeconf['ports']:
      if not p in newconf['ports'] and 'port-channel' in p.lower():
        yield "no interface %s" % p



  def genSyncAll(self, newconf):
    logging.debug("Configuration read in progress for host %s ..." % self.hostname)
    actcfgo = OS10Parser(self.getRunning().splitlines())
    activeconf = actcfgo.getConfStruct()
    logging.debug("Configuration parsed for host %s ." % self.hostname)
    res = []
    if 'vlans' in newconf:
      res += list(self.genSyncVLANS(newconf, activeconf))
    if 'ports' in newconf:
      res += list(self.genSyncPhysPorts(newconf, activeconf))
      res += list(self.genSyncPortChannels(newconf, activeconf))
    return res

