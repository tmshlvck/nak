#!/usr/bin/env python3
# coding: utf-8

"""
nak.cisco

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
import ipaddress

import nak


class CiscoLikeParser(nak.BasicParser):
  def __init__(self, config):
    self.cfg = OrderedDict()
    self.parseConfig(config)


  @classmethod
  def _normalize_vlan_list(cls, v):   
    v = v.strip()

    try:
      return [int(v)]
    except:
      pass

    m = re.match(r'^([0-9]+)-([0-9]+)$', v)
    if m:
      return list(range(int(m.group(1)), int(m.group(2))+1))

    spl = v.split(',')
    if len(spl) > 1:
      r = []
      for e in spl:
        nv = cls._normalize_vlan_list(e)
        if type(nv) is list:
          r += nv
        else:
          r.append(nv)
      return r

    if type(v) is list:
      return v
    else:
      return [v]


  @classmethod
  def _parse_users(cls, cp):
    users = OrderedDict()
    
    for o in cp.find_objects(r"^\s*username\s+.+"):
      u = o.re_match_typed(r"^\s*username\s+(.+)$").strip()
      m = re.match(r'^\s*(\S+)\s+(.*)$', u)
      if m:
        username = m.group(1)
        if not username in users:
          users[username] = []
        users[username].append(m.group(2))
 
    return users

  @classmethod
  def _parse_address(cls, addr):
    mi = re.match(r"^\s*([0-9\.]+) ([0-9\.]+)( secondary)?$", addr)
    if mi:
      return str(ipaddress.ip_interface('%s/%s' % (mi.group(1), mi.group(2))))
    mi = re.match(r"^\s*([0-9a-fA-F:\.]+)/([0-9]+)( secondary)?$", addr)
    if mi:
      return str(ipaddress.ip_interface('%s/%s' % (mi.group(1), mi.group(2))))

    return None


class IOSParser(CiscoLikeParser):
  def __init__(self, config):
    self.cfg = OrderedDict()
    self.parseConfig(config)


  @classmethod
  def _iface_filter(cls, ifname, iface):
    if 'mgmt' in ifname:
      return False

    if 'Vlan' in ifname:
      return False

    if 'vpc-peer-link' in iface:
      return False

    return True


  @classmethod
  def _parse_if_line(cls, c, iface):
    """c = CiscConfParse children object (=line)
    iface = OrderedDict resulting structure
    """

    m = c.re_match_typed(r"^\s*description\s+(.+)$").strip()
    if m:
      iface['descr'] = m
      return

    m = c.re_match_typed(r"^\s*(shutdown)\s*$")
    if m:
      iface['shutdown'] = True
      return

    m = c.re_match_typed(r"^\s*switchport mode\s+(.+)$")
    if m:
      iface['type'] = m
      return

    m = c.re_match_typed(r"^\s*switchport access vlan\s+([0-9]+)\s*$")
    if m:
      iface['access_vlan'] = int(m)
      return

    m = c.re_match_typed(r"^\s*switchport trunk native vlan\s+([0-9]+)\s*$")
    if m:
      iface['native_vlan'] = int(m)
      return

    m = c.re_match_typed(r"^\s*switchport trunk encapsulation\s+(.+)\s*$")
    if m:
      iface['encap'] = m
      return

    m = c.re_match_typed(r"^\s*switchport trunk allowed vlan add\s+(.+)$")
    if m:
      iface['allowed_vlan'] += cls._normalize_vlan_list(m)
      return

    m = c.re_match_typed(r"^\s*switchport trunk allowed vlan\s+(.+)$")
    if m:
      iface['allowed_vlan'] = cls._normalize_vlan_list(m)
      return

    m = c.re_match_typed(r'^\s*(no\s+switchport)\s*$')
    if m:
      iface['type'] = 'no switchport'
      return

    m = c.re_match_typed(r'^\s*ip address\s+(.+)')
    if m:
      iface['type'] = 'no switchport'
      a = cls._parse_address(m)
      if not 'ip_addr' in iface:
        iface['ip_addr'] = []
      iface['ip_addr'].append(a)
      return

    m = c.re_match_typed(r'^\s*ipv6 address\s+(.+)')
    if m:
      iface['type'] = 'no switchport'
      a = cls._parse_address(m)
      if not 'ipv6_addr' in iface:
        iface['ipv6_addr'] = []
      iface['ipv6_addr'].append(a)
      return

    m = c.re_match_typed(r'^\s*channel-group\s+(.+)')
    if m:
      mi = re.match(r'^\s*([0-9]+)\s+mode\s+(\S.+)$', m)
      if mi:
        iface['lag'] = int(mi.group(1))
        iface['lagmode'] = mi.group(2).strip()
      else:
        iface['lag'] = int(m)
        iface['lagmode'] = 'on'
      return

    # Nexus specific: TODO move to NXOS object
    m = c.re_match_typed(r'^\s*vpc\s+(.*)\s*$')
    if m:
      if m.strip() == 'peer-link':
        iface['vpc-peer-link'] = True
      else:
        iface['mlag'] = int(m)
      return
       
    m = c.re_match_typed(r'^\s*mtu\s+([0-9]+)\s*$')
    if m:
      iface['mtu'] = int(m)
      return

    if not 'extra' in iface:
      iface['extra'] = []
    iface['extra'].append(c.text.strip())


  @classmethod
  def _parse_if(cls, o, iface):
    """o = CiscConfParse object
    iface = OrderedDict resulting structure
    """

    for c in o.children:
      cls._parse_if_line(c, iface)


  @classmethod
  def _parse_ifaces(cls, cp, active_vlans):
    ifaces = OrderedDict()

    for o in cp.find_objects(r"^\s*interface"):
      name = o.re_match_typed(r"^\s*interface\s+(.+)$").strip()
      if not name:
        raise Exception("Wrong interface: %s" % str(o))

      if not name in ifaces:
        ifaces[name] = OrderedDict()
        ifaces[name]['shutdown'] = False
        ifaces[name]['type'] = 'access'

      cls._parse_if(o, ifaces[name])

    # General cleanup
    to_remove = []
    for ifname in ifaces:
      i = ifaces[ifname]

      if i['type'] == 'access':
        i['untagged'] = (i['access_vlan'] if 'access_vlan' in i else 1)
      elif i['type'] == 'trunk':
        i['untagged'] = (i['native_vlan'] if 'native_vlan' in i else 1) # TODO: Cisco can change native VLAN globally
        if 'allowed_vlan' in i and i['allowed_vlan']:
          i['tagged'] = sorted(list(set(i['allowed_vlan']) - {i['untagged']}))
        else:
          i['tagged'] = 'all'

      i.pop('access_vlan', None)
      i.pop('native_vlan', None)
      i.pop('allowed_vlan', None)

      if 'lag' in i:
        i.pop('untagged', None)
        i.pop('tagged', None)

      if not cls._iface_filter(ifname, i):
        to_remove.append(ifname)

      if not cls._is_iface_configured(i):
        ifaces[ifname] = OrderedDict()
        ifaces[ifname]['clean'] = True

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces


  @classmethod
  def _is_iface_configured(cls, p):
    if 'descr' in p:
      return True
    if 'tagged' in p:
      return True
    if 'untagged' in p and p['untagged'] != 1:
      return True
    if 'shutdown' in p and p['shutdown']:
      return False

    return True


  @classmethod
  def _parse_vlans(cls, cp):
    vlans = OrderedDict()
    
    for o in cp.find_objects(r"^\s*vlan\s+([0-9,-]+)"):
      vids = o.re_match_typed(r"^\s*vlan\s+([0-9,-]+)\s*$").strip()
      if not vids:
        raise Exception("Wrong vlan: %s" % str(o))

      for vids in cls._normalize_vlan_list(vids):
        vid = int(vids)

        if not vid in vlans:
          vlans[vid] = OrderedDict()

        for c in o.children:
          m = c.re_match_typed(r"^\s*name\s+(.+)$", result_type=str)
          if m:
            vlans[vid]['name'] = m
            continue
        
          logging.debug("Ignored: %s", c.text)

    return vlans


  @classmethod
  def _parse_bgp(cls, cp):
    def setup_nb(nbip, nghbs):
      if not nbip in nghbs:
        nghbs[nbip] = OrderedDict()
        nghbs[nbip]['shutdown'] = False

    def decrypt_type7(pw):
      # Copyright (c) 2016 Richy Strnad
      # MIT license - TODO: figure out licencing impact on the whole NAK
      salt = 'dsfd;kfoA,.iyewrkldJKDHSUBsgvca69834ncxv9873254k;fg87'
      # The first 2 digits represent the salt index salt[index]
      index = int(pw[:2])
      # The rest of the string is the encrypted password
      enc_pw = pw[2:].rstrip()
      # Split the pw string into the hex chars, each cleartext char is two hex chars
      hex_pw = [enc_pw[i:i+2] for i in range(0, len(enc_pw), 2)]
      # Create the cleartext list
      cleartext = []
      # Iterate over the hex list
      for i in range(0, len(hex_pw)):
        '''
        The current salt index equals the starting index + current itteration
        floored by % 53. This is to make sure that the salt index start at 0
        again after it reached 53.
        '''
        cur_index = (i+index) % 53
        # Get the current salt
        cur_salt = ord(salt[cur_index])
        # Get the current hex char as int
        cur_hex_int = int(hex_pw[i], 16)
        # XOR the 2 values (this is the decryption itself, XOR of the salt + encrypted char)
        cleartext_char = cur_salt ^ cur_hex_int
        # Get the char for the XOR'ed INT and append it to the cleartext List
        cleartext.append(chr(cleartext_char))
      return ''.join(cleartext)

    def parse_neighbor(l, nghbs, afi):
#      print("D:" + str(l))
      m = re.match(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+remote-as\s+([0-9]+).*$', l.text)
      if m:
        nb = m.group(1)
        setup_nb(nb, nghbs)
        nghbs[nb]['remote-as'] = int(m.group(2))

      m = re.match(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+description\s+(.+)$', l.text)
      if m:
        nb = m.group(1)
        setup_nb(nb, nghbs)
        nghbs[nb]['descr'] = m.group(2).strip()

      m = re.match(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+peer-group\s+(.+)$', l.text)
      if m:
        nb = m.group(1)
        setup_nb(nb, nghbs)
        nghbs[nb]['peer-group'] = m.group(2).strip()

      m = re.match(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+password\s+7\s+(.+)$', l.text)
      if m:
        nb = m.group(1)
        setup_nb(nb, nghbs)
        nghbs[nb]['password'] = decrypt_type7(m.group(2).strip())

      m = re.match(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+shutdown.*$', l.text)
      if m:
        nb = m.group(1)
        setup_nb(nb, nghbs)
        nghbs[nb]['shutdown'] = True

      m = re.match(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+activate\s*$', l.text)
      if m:
        nb = m.group(1)
        setup_nb(nb, nghbs)
        if not 'afi' in nghbs[nb]:
          nghbs[nb]['afi'] = []
        nghbs[nb]['afi'].append((af if af else 'ipv4'))
         

    bgp = OrderedDict()
    for o in cp.find_objects(r'^\s*router\s+bgp\s+([0-9]+)'):
      local_asn = int(o.re_match_typed(r'^\s*router\s+bgp\s+([0-9]+)').strip())
      bgp[local_asn] = OrderedDict()
      for c in o.children:
        if c.re_match_typed(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+.*'):
          parse_neighbor(c, bgp[local_asn], None)
          continue

        af = c.re_match_typed(r'^\s*address-family\s+(.+)$')
        if af:
          for afc in c.children:
            if afc.re_match_typed(r'^\s*neighbor\s+([a-fA-F0-9\.:]+)\s+.*'):
              parse_neighbor(afc, bgp[local_asn], af)

    return bgp


  def parseConfig(self, conffile):
    cp = ciscoconfparse.CiscoConfParse(conffile)

    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))
    if not o:
      raise ValueError("Can not parse config without hostname")
    hostname = o[0].re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    self.cfg['hostname'] = hostname

    vlans = self._parse_vlans(cp)
    self.cfg['vlans'] = vlans
    self.cfg['ports'] = self._parse_ifaces(cp, vlans)
    self.cfg['users'] = self._parse_users(cp)
    bgpr = self._parse_bgp(cp)
    if bgpr:
      self.cfg['bgp'] = bgpr


class NXOSParser(IOSParser):
  @classmethod
  def _parse_if_line(cls, c, iface):
    """c = CiscConfParse children object (=line)
    iface = OrderedDict resulting structure
    """

    m = c.re_match_typed(r'^\s*vpc\s+(.*)\s*$')
    if m:
      if m.strip() == 'peer-link':
        iface['vpc-peer-link'] = True
      else:
        iface['mlag'] = int(m)
      return

    IOSParser._parse_if_line(c, iface)


class IOSBox(nak.BasicGen,nak.Box):
  IGNORE_VLANS = [1,1002, 1003, 1004, 1005]

  def __init__(self):
    super().__init__("ios")


  def genSyncVLANS(self, newconf, activeconf):
    for vid in set(activeconf['vlans'])-set(newconf['vlans']):
      if not vid in self.IGNORE_VLANS:
        yield "no vlan %d" % vid

    for vid in newconf['vlans']:
      if newconf['vlans'][vid] == activeconf['vlans'].get(vid, None):
        continue

      if not vid in self.IGNORE_VLANS:
        yield "vlan %d" % vid
        if 'name' in newconf['vlans'][vid]:
          yield " name %s" % self._normalize_namestr(newconf['vlans'][vid]['name'])
        yield '!'


  @classmethod
  def _expand_tagged_vlans(cls, conf, p):
    if not p in conf['ports']:
      return None

    pd = conf['ports'][p]
    if 'tagged' in pd:
      if not pd['tagged']:
        return None

      if type(pd['tagged']) is str:
        if (pd['tagged'].lower() == 'all' or pd['tagged'] == '*'):
            return None
        else:
          raise ValueError('Unsupported tagged value:' % tgt)
      else:
        if 'untagged' in pd:
          try:
            pd['tagged'] = list((set(pd['tagged']) | {pd['untagged'],}))
          except:
            print('DEBUG: Exception in %s %s'%(str(p),str(pd)))
            raise
        return list(self._compact_int_list(pd['tagged']))
    else:
      return None


  def _genPhysPortConfig(self, pd, newconf, activeconf):
    if 'descr' in pd and pd['descr']:
      yield " description %s" % pd['descr']

    if 'shutdown' in pd and pd['shutdown']:
      yield " shutdown"
    else:
      yield " no shutdown"

    if 'lag' in pd:
      pcn = 'Port-channel%d' % pd['lag']
      if pcn in newconf['ports']:
        pd['type'] = newconf['ports'][pcn]['type']
        pd['tagged'] = newconf['ports'][pcn]['tagged']
        pd['untagged'] = newconf['ports'][pcn]['untagged']

    if 'type' in pd:
      if pd['type'] == 'access':
        yield " switchport mode access"
        yield " switchport access vlan %d" % pd['untagged']
      elif pd['type'] == 'trunk':
        if 'encap' in pd and pd['encap']:
          yield " switchport trunk encapsulation %s" % pd['encap']
        yield " switchport mode trunk"
 
        if 'untagged' in p:
          yield " switchport trunk native vlan %d" % pd['untagged']

        tgt = self._expand_tagged_vlans(newconf, p)
        acttagged = self._expand_tagged_vlans(activeconf, p)

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
      yield " mtu %d" % pd['mtu']

    if 'lag' in pd:
      yield " channel-group %d mode %s" % (pd['lag'], (pd['lagmode'] if 'lagmode' in pd else "on"))

    if 'extra' in pd:
      for e in pd['extra']:
        yield " %s" % e


  def genSyncPhysPorts(self, newconf, activeconf, pattern="Ethernet"):
    for p in newconf['ports']:
      pd = newconf['ports'][p]

      if not pattern in p:
        continue

      if not type(pd) is dict:
        logging.debug("Skipping port with not config %s", p)
        continue

      if pd == activeconf['ports'].get(p, None):
        logging.debug("Skipping no-change configuration for port %s", p)
        continue

      if 'clean' in pd and pd['clean'] == True:
        yield "default interface %s" % p
        yield "interface %s" % p
        yield " shutdown"
        yield "!"
        continue

      yield "interface %s " % p
      self._genPhysPortConfig(pd, newconf, activeconf)
      yield "!"


  def genSyncPortChannels(self, newconf, activeconf):
    for p in newconf['ports']:
      pd = newconf['ports'][p]

      if pd and type(pd) is dict:
        if 'clean' in pd and pd['clean'] and 'Port-channel' in p:
          yield "no interface %s" % p

    for p in activeconf['ports']:
      if not p in newconf['ports'] and 'Port-channel' in p:
        yield "no interface %s" % p

    for r in self.genSyncPhysPorts(newconf, activeconf, pattern="Port-channel"):
      yield r


  def genSyncBGP(self, newconf, activeconf, regen=False):
    res = []
    change = False

    for localas in newconf['bgp']:
      if not 'bgp' in activeconf:
        change = True
        activeconf['bgp'] = {}
      if not localas in activeconf['bgp']:
        change = True
        activeconf['bgp'][localas] = {}

      rtr = newconf['bgp'][localas]
      res.append("router bgp %d" % localas)

      for nbip in rtr:
        if not nbip in activeconf['bgp'][localas] or rtr[nbip] != activeconf['bgp'][localas][nbip]:
          change = True
          for afi in rtr[nbip]['afi']:
            res.append('address-family %s' % afi)
            res.append('neighbor %s remote-as %d' % (nbip, rtr[nbip]['remote-as']))
            if 'peer-group' in rtr[nbip]:
              res.append('neighbor %s peer-group %s' % (nbip, rtr[nbip]['peer-group']))
            if 'descr' in rtr[nbip]:
              res.append('neighbor %s description %s' % (nbip, rtr[nbip]['descr']))
            if 'password' in rtr[nbip]:
              res.append('neighbor %s password %s' % (nbip, rtr[nbip]['password']))
            res.append('!')

      for nbip in activeconf['bgp'][localas]:
        if not nbip in rtr:
          change = True
          res.append('no neigrbor %s' % nbip)

    if change or regen:
      return res
    else:
      return []


  def genSyncAll(self, newconf, activeconf):
    logging.debug("Generating configuration for host %s ." % self.hostname)
    res = []
    if 'vlans' in newconf:
      res += list(self.genSyncVLANS(newconf, activeconf))
    if 'ports' in newconf:
      res += list(self.genSyncPhysPorts(newconf, activeconf))
      res += list(self.genSyncPortChannels(newconf, activeconf))
    if 'bgp' in newconf:
      res += list(self.genSyncBGP(newconf, activeconf))
    return res


class NXOSBox(IOSBox):
  def _genPhysPortConfig(self, pd, newconf, activeconf):
    super()._genPhysPortConfig(pd, newconf, activeconf)

    if 'mlag' in pd:
      yield "vpc %s" % str(pd['mlag'])

