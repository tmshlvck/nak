#!/usr/bin/env python3

import ciscoconfparse
import yaml
import re
from collections import OrderedDict,defaultdict
import nak.ios
from nak import d


class IronwareParser(nak.ios.CiscoLikeParser):
  def __init__(self, config):
    self.cfg = OrderedDict()
    self.parseConfig(config)


  @classmethod
  def _iface_filter(cls, ifname, iface):
    if 'ethernet' in ifname:
      return True

    if 'lag' in ifname:
      return True

    return False


  @classmethod
  def _ifindex_range(cls, start, end):
    ms = re.match(r'^\s*([0-9/]+/)?([0-9]+)\s*$', start)
    me = re.match(r'^\s*([0-9/]+/)?([0-9]+)\s*$', end)
    if ms and me and ms.group(1) == me.group(1):
      mspfx = ms.group(1)
      mepfx = me.group(1)
      if mspfx == mepfx:
        s = int(ms.group(2))
        e = int(me.group(2))
        if not mspfx:
          mspfx = mepfx = ''
      else:
        raise ValueError("Can not expand multi-level range: start=%s end=%s" % (str(start), str(end)))
      return ['%s%d' % (mspfx, i) for i in range(s,e+1)]
    else:
      raise ValueError("Can not parse: start=%s end=%s" % (str(start), str(end)))

  @classmethod
  def _normalize_iflist(cls, rng):
    if not rng.strip():
      return

    m = re.match(r'^\s*(ethe|ethernet)\s+([0-9/]+)\s+to\s+([0-9/]+)(\s+.*)?$', rng)
    if m:
      for i in cls._ifindex_range(m.group(2), m.group(3)):
        yield 'ethernet_%s' % i
      rest = m.group(4)
      if rest:
        for r in cls._normalize_iflist(rest):
          yield r
      return

    m = re.match(r'^\s*(ethe|ethernet)\s+([0-9/]+)(\s.*)?$', rng)
    if m:
      yield 'ethernet_%s' % m.group(2)
      rest = m.group(3)
      if rest:
        for r in cls._normalize_iflist(rest):
          yield r
      return

    raise ValueError("Unknown interface: %s" % str(rng))


  @classmethod
  def _parse_ifaces(cls, cp):
    ifaces = OrderedDict()

    for o in cp.find_objects(r"^\s*interface"):
      name = o.re_match_typed(r"^\s*interface\s+(.+)$").strip().replace(' ', '_')
      if not name:
        raise Exception("Wrong interface: %s" % str(o))

      if not name in ifaces:
        ifaces[name] = OrderedDict()
        ifaces[name]['shutdown'] = False

      for c in o.children:
        m = c.re_match_typed(r"^\s*port-name\s+(.+)$").strip('" ')
        if m:
          ifaces[name]['descr'] = m
          continue

        m = c.re_match_typed(r"^\s*(disable)\s*$")
        if m:
          ifaces[name]['shutdown'] = True
          continue

        m = c.re_match_typed(r'^\s*(dual-mode.*)$')
        if m:
          im = re.match(r'^\s*dual-mode(.*)', m)
          if im:
            if im.group(1):
              ifaces[name]['untagged'] = int(im.group(1).strip())
            else:
              ifaces[name]['untagged'] = 1
        
        d("Ignored: %s" % (c.text))

    for ifname in ifaces:
      if not 'untagged' in ifaces[ifname]:
        ifaces[ifname]['untagged'] = 1

    return ifaces


  @classmethod
  def _cleanup_ifaces(cls, ifaces):
  # fill gaps
    for ifname in ifaces:
      i = ifaces[ifname]
      if 'tagged' in i:
        i['tagged'] = sorted(i['tagged'])

      if not 'untagged' in i:
        i['untagged'] = 1

      if not 'type' in i:
        if 'tagged' in i:
          ifaces[ifname]['type'] = 'trunk'
        else:
          ifaces[ifname]['type'] = 'access'

      if i['type'] == 'access' and i['untagged'] == 1 and not 'lag' in i and not 'descr' in i and i['shutdown']:
        ifaces[ifname] = OrderedDict()
        ifaces[ifname]['clear'] = True
        continue

    # remove virtual ifaces
    to_remove = []
    for ifname in ifaces:
      if not cls._iface_filter(ifname, ifaces[ifname]):
        to_remove.append(ifname)

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces


  @classmethod
  def _parse_vlans(cls, cp, ifaces):
    """
vlan 16 name TI-Management by port
 tagged ethe 1/1/1 to 1/1/3 ethe 1/1/6 ethe 1/1/9 ethe 1/1/19 ethe 1/1/23 ethe 1/3/1 to 1/3/3 ethe 1/3/5 to 1/3/8 ethe 2/1/1 ethe 2/1/11 ethe 2/1/13 ethe 2/1/16 ethe 2/1/19 ethe 2/1/23 ethe 2/3/1 to 2/3/3 ethe 2/3/5 to 2/3/8
 untagged ethe 1/1/14 ethe 1/1/17 to 1/1/18 ethe 2/1/17 to 2/1/18
 spanning-tree 802-1w
 spanning-tree 802-1w priority 32767
    """

    vlans = OrderedDict()
    
    for o in cp.find_objects(r"^\s*vlan\s+(.+)"):
      vlanstr = o.re_match_typed(r"^\s*vlan\s+(.+)$").strip()
      if not vlanstr:
        raise Exception("Wrong vlan: %s" % str(o))

      m = re.match(r'^\s*([0-9]+)(\s+name\s+(\S+))?(\s.*)?', vlanstr)
      if m:
        vid = int(m.group(1))
        if not vid in vlans:
          vlans[vid] = OrderedDict()
        n = m.group(3)
        if n:
           vlans[vid]['name'] = n.strip()
      else:
        raise ValueError(str(o))

      for c in o.children:
        m = c.re_match_typed(r'^\s*tagged\s+(.*)$').strip()
        if m:
          for t in cls._normalize_iflist(m):
            ifname = str(t)
            if not ifname in ifaces:
              ifaces[ifname] = OrderedDict()
              ifaces[ifname]['shutdown'] = False
              
            ifaces[ifname]['type'] = 'trunk'
            if not 'tagged' in ifaces[ifname]:
              ifaces[ifname]['tagged'] = []
            if not ('untagged' in ifaces[ifname] and vid == ifaces[ifname]['untagged']):
              ifaces[ifname]['tagged'].append(vid)

          continue
          
        m = c.re_match_typed(r'^\s*untagged\s+(.*)$').strip()
        if m:
          for t in cls._normalize_iflist(m):
            ifname = str(t)
            if not ifname in ifaces:
              ifaces[ifname] = OrderedDict()
              ifaces[ifname]['shutdown'] = False
              
            if not 'type' in ifaces[ifname]:
              ifaces[ifname]['type'] = 'access'

            ifaces[ifname]['untagged'] = vid

          continue
        
        d("Ignored: %s" % (c.text))

    return vlans


  @classmethod
  def _parse_trunks(cls, cp, ifaces):
    """
lag "ti-ds1" dynamic id 2
 ports ethernet 1/3/8 ethernet 2/3/8
    """

    for o in cp.find_objects(r"^\s*lag"):
      m = o.re_match_typed(r"^\s*lag\s+(.*$)").strip()
      mi = re.match(r'^\s*(\S+)\s+(\S+)\s+id\s+([0-9]+)', m)

      trkname = 'lag_%d' % int(mi.group(3))
      if not trkname in ifaces:
        ifaces[trkname] = OrderedDict()
        ifaces[trkname]['shutdown'] = False

      ifaces[trkname]['descr'] = mi.group(1).strip('" ')
      if mi.group(2).strip() == 'dynamic':
        lagmode = 'active'
      else:
        lagmode = 'on'


      for c in o.children:
        m = c.re_match_typed(r"^\s*primary-port\s+([0-9/]+)\s*$").strip()
        if m:
          ifname = 'ethernet_%s' % m
          if 'tagged' in ifaces[ifname]:
            ifaces[trkname]['tagged'] = ifaces[ifname]['tagged']
          ifaces[trkname]['untagged'] = ifaces[ifname]['untagged']

      for c in o.children:
        m = c.re_match_typed(r"^\s*ports\s+(.+)$").strip()
        if m:
          for ifname in cls._normalize_iflist(m):
            if not ifname in ifaces:
              ifaces[ifname] = OrderedDict()

            if not 'shutdown' in ifaces[ifname]:
              ifaces[ifname]['shutdown'] = False
            ifaces[ifname]['lag'] = trkname
            ifaces[ifname]['lagmode'] = lagmode

            ifaces[ifname].pop('tagged', None)
            ifaces[ifname].pop('untagged', None)


  def parseConfig(self, conffile):
    cp = ciscoconfparse.CiscoConfParse(conffile)
    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))[0]
    hostname = o.re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    self.cfg['hostname'] = hostname
    ports = self._parse_ifaces(cp)
    self.cfg['vlans'] = self._parse_vlans(cp, ports)
    self._parse_trunks(cp, ports)
    self.cfg['ports'] = self._cleanup_ifaces(ports)
    self.cfg['users'] = self._parse_users(cp)

