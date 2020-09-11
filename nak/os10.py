#!/usr/bin/env python3

import ciscoconfparse
import re
from collections import OrderedDict,defaultdict
import logging

import nak
import nak.ios



class OS10Parser(nak.ios.CiscoLikeParser):
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
          ifaces[name]['no-switchport'] = True
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

      if 'no-switchport' in i and not 'lag' in i: # remove L3 and MLAG discovery ports but not MLAG downlinks
        to_remove.append(ifname)

      i.pop('no-switchport', None)

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





class OS10Gen(nak.BasicGen):
  IGNORE_VLANS = [1,]
  TEMPLATE = 'dellos10.j2'
  CFG_VLAN_RANGE = range(2,4094)

  def _hooks(self):
    super()._hooks()

    self.conf['remove_vlans'] = list(self._compact_int_list(self.conf['remove_vlans']))

    if not 'remove_ports' in self.conf:
      self.conf['remove_ports'] = []

    for p in self.conf['ports']:
      pd = self.conf['ports'][p]
      if 'tagged' in pd:
        pd['tagged'] = self._compact_int_list(pd['tagged'])

      if 'clean' in pd and pd['clean'] and 'port-channel' in p.lower():
        self.conf['remove_ports'].append(p)

    for p in self.conf['remove_ports']:
      del(self.conf['ports'][p])

