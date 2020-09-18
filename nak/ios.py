#!/usr/bin/env python3

import ciscoconfparse
import re
from collections import OrderedDict,defaultdict
import logging

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

    if 'no-switchport' in iface:
      return False

    return True
  

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

        m = c.re_match_typed(r"^\s*switchport trunk native vlan\s+([0-9]+)\s*$")
        if m:
          ifaces[name]['native_vlan'] = int(m)
          continue

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan add\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] += cls._normalize_vlan_list(m)
          continue

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] = cls._normalize_vlan_list(m)
          continue

        m = c.re_match_typed(r'^\s*(no\s+switchport)\s*$')
        if m:
          ifaces[name]['no-switchport'] = True

        m = c.re_match_typed(r'^\s*channel-group\s+(.+)')
        if m:
          mi = re.match(r'^\s*([0-9]+)\s+mode\s+(\S.+)$', m)
          if mi:
            ifaces[name]['lag'] = int(mi.group(1))
            ifaces[name]['lagmode'] = mi.group(2).strip()
          else:
            ifaces[name]['lag'] = int(m)
            ifaces[name]['lagmode'] = 'on'
 
        m = c.re_match_typed(r'^\s*vpc\s+(.*)\s*$')
        if m:
          if m.strip() == 'peer-link':
            ifaces[name]['vpc-peer-link'] = True
          else:
            ifaces[name]['mlag'] = int(m)
        
        m = c.re_match_typed(r'^\s*mtu\s+([0-9]+)\s*$')
        if m:
          ifaces[name]['mtu'] = int(m)
 
        logging.debug("Ignored: %s", c.text)

    to_remove = []
    for ifname in ifaces:
      i = ifaces[ifname]

      if i['type'] == 'access':
        i['untagged'] = (i['access_vlan'] if 'access_vlan' in i else 1)
      elif i['type'] == 'trunk':
        i['untagged'] = (i['native_vlan'] if 'native_vlan' in i else 1) # TODO: Cisco can change native VLAN globally
        if not 'allowed_vlan' in i:
          i['allowed_vlan'] = active_vlans.keys()
        i['tagged'] = sorted(list(set(i['allowed_vlan']) - {i['untagged']}))
        if not i['tagged']:
          i['tagged'] = 'all'

      i.pop('access_vlan', None)
      i.pop('native_vlan', None)
      i.pop('allowed_vlan', None)

      if 'lag' in i:
        i.pop('untagged', None)
        i.pop('tagged', None)

      if 'no-switchport' in i:
        to_remove.append(ifname)

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


class IOSBox(nak.BasicGen,nak.Box):
  IGNORE_VLANS = [1,1002, 1003, 1004, 1005]

  def __init__(self):
    super().__init__("ios")


  def genSyncVLANS(self, newconf, activeconf):
    for vid in set(activeconf['vlans'])-set(newconf['vlans']):
      if not vid in self.IGNORE_VLANS:
        yield "no vlan %d" % vid

    for vid in newconf['vlans']:
      if not vid in self.IGNORE_VLANS:
        yield "vlan %d" % vid
        if 'name' in newconf['vlans'][vid]:
          yield " name %s" % self._normalize_namestr(newconf['vlans'][vid]['name'])
        yield '!'


  def genSyncPhysPorts(self, newconf, activeconf, pattern="Ethernet"):
    def _expand_tagged_vlans(conf, p):
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


    for p in newconf['ports']:
      pd = newconf['ports'][p]

      if not pattern in p:
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

          tgt = _expand_tagged_vlans(newconf, p)
          acttagged = _expand_tagged_vlans(activeconf, p)

          if tgt:
            if tgt != acttagged:
              yield " no switchport trunk allowed vlan"
              yield " switchport trunk allowed vlan %s" % ",".join([str(v) for v in tgt])
          else:
            yield " no switchport trunk allowed vlan"

        elif pd['type'] == 'no switchport':
          yield "no switchport"
        else:
          raise ValueError("Unknown port %s type: %s" % (p, pd['type']))
      else:
        raise ValueError("Missing port type for %s" % p)

      if 'mtu' in pd:
        yield " mtu %d" % pd['mtu']

      if 'mlag' in pd:
        yield "vpc %s" % str(pd['mlag'])

      if 'lag' in pd:
        yield " channel-group %d mode %s" % (pd['lag'], (pd['lagmode'] if 'lagmode' in pd else "on"))

      if 'extra' in pd:
        for e in pd['extra']:
          yield " %s" % e

      yield "!"


  def genSyncPortChannels(self, newconf, activeconf):
    for p in newconf['ports']:
      pd = newconf['ports'][p]
      if 'clean' in pd and pd['clean'] and 'Port-channel' in p:
        yield "no interface %s" % p

    for r in self.genSyncPhysPorts(newconf, activeconf, pattern="Port-channel"):
      yield r


  def genSyncAll(self, newconf):
    logging.debug("Configuration read in progress for host %s ..." % self.hostname)
    actcfgo = IOSParser(self.getRunning().splitlines())
    activeconf = actcfgo.getConfStruct()
    logging.debug("Configuration parsed for host %s ." % self.hostname)
    res = []
    res += list(self.genSyncVLANS(newconf, activeconf))
    res += list(self.genSyncPhysPorts(newconf, activeconf))
    res += list(self.genSyncPortChannels(newconf, activeconf))
    return res


class NXOSBox(IOSBox):
  pass

