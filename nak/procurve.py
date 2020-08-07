#!/usr/bin/env python3

import ciscoconfparse
import re
from collections import OrderedDict,defaultdict
import nak
import nak.ios
from nak import d


        
 


class ProCurveParser(nak.ios.CiscoLikeParser):
  def __init__(self, config):
    self.cfg = OrderedDict()
    self.parseConfig(config)


  @classmethod
  def _iface_filter(cls, ifname, iface):
    return True
  

  @classmethod
  def _parse_ifaces(cls, cp):
    ifaces = OrderedDict()

    for o in cp.find_objects(r"^\s*interface"):
      name = o.re_match_typed(r"^\s*interface\s+(.+)$").strip()
      if not name:
        raise Exception("Wrong interface: %s" % str(o))

      if not name in ifaces:
        ifaces[name] = OrderedDict()
        ifaces[name]['shutdown'] = False

      for c in o.children:
        m = c.re_match_typed(r"^\s*name\s+(.+)$").strip('" ')
        if m:
          ifaces[name]['descr'] = m
          continue

        m = c.re_match_typed(r"^\s*(disable)\s*$")
        if m:
          ifaces[name]['shutdown'] = True
          continue

        m = c.re_match_typed(r'^\s*(no\s+lacp)')
        if m:
          ifaces[name]['lagmode'] = 'on'
          continue
        
        d("Ignored: %s" % (c.text))


    for o in cp.find_objects(r"^\s*trunk"):
      trk = o.re_match_typed(r"^\s*trunk\s+(.+)$").strip()
      if not name:
        raise Exception("Wrong interface: %s" % str(o))

      mi = re.match(r'^\s*([0-9,-]+)\s+(\S+)(\s+.*)', m)
      if mi:
        trkname = mi.group(2).strip()
        for name in cls._normalize_vlan_list(mi.group(1)): # using _normalize_vlan_list is a hack
          if not name in ifaces:
            ifaces[name] = OrderedDict()
          if not 'shutdown' in ifaces[name]:
            ifaces[name]['shutdown'] = False
          ifaces[name]['lag'] = trkname

          ifaces[name].pop('untagged', None)
          ifaces[name].pop('tagged', None)



        if not trkname in ifaces:
            ifaces[trkname] = OrderedDict()
            ifaces[trkname]['shutdown'] = False

    to_remove = []
    for ifname in ifaces:
      if not cls._iface_filter(ifname, ifaces[ifname]):
        to_remove.append(ifname)

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces

  @classmethod
  def _parse_vlans(cls, cp, ifaces):
    vlans = OrderedDict()
    
    for o in cp.find_objects(r"^\s*vlan\s+([0-9,-]+)"):
      vidstr = o.re_match_typed(r"^\s*vlan\s+([0-9,-]+)\s*$").strip()
      if not vidstr:
        raise Exception("Wrong vlan: %s" % str(o))

      for vidstr in cls._normalize_vlan_list(vidstr):
        vid = int(vidstr)

        if not vid in vlans:
          vlans[vid] = OrderedDict()

        for c in o.children:
          m = c.re_match_typed(r"^\s*name\s+(.+)$")
          if m:
            vlans[vid]['name'] = m.strip('" ')
            continue

          m = c.re_match_typed(r'^\s*tagged\s+(.*)$').strip()
          if m:
            for t in cls._normalize_vlan_list(m):
              ifname = str(t)
              if not ifname in ifaces:
                ifaces[ifname] = OrderedDict()
                ifaces[ifname]['shutdown'] = False
              
              ifaces[ifname]['type'] = 'trunk'
              if not 'tagged' in ifaces[ifname]:
                ifaces[ifname]['tagged'] = []
              ifaces[ifname]['tagged'].append(vid)
            
            continue
          
          m = c.re_match_typed(r'^\s*untagged\s+(.*)$').strip()
          if m:
            for t in cls._normalize_vlan_list(m):
              ifname = str(t)
              if not ifname in ifaces:
                ifaces[ifname] = OrderedDict()
                ifaces[ifname]['shutdown'] = False
              
              if not 'type' in ifaces[ifname]:
                ifaces[ifname]['type'] = 'access'

              ifaces[ifname]['untagged'] = vid

            continue
        
          d("Ignored: %s" % (c.text))

    # fill gaps
    for ifname in ifaces:
      i = ifaces[ifname]
      if 'tagged' in i:
        i['tagged'] = sorted(i['tagged'])

      if not 'untagged' in i:
        i['untagged'] = 1

      # mark clear ifaces
      if (not 'type' in i or i['type'] == 'access') and i['untagged'] == 1 and not 'lag' in i and not 'descr' in i and i['shutdown']:
        ifaces[ifname] = OrderedDict()
        ifaces[ifname]['clear'] = True
        continue

    return vlans


  @classmethod
  def _parse_users(cls, cp):
    users = OrderedDict()
    
    for o in cp.find_objects(r"^\s*password\s+.+"):
      u = o.re_match_typed(r"^\s*password\s+(.+)$").strip()
      users[u] = OrderedDict()
 
    return users


  def parseConfig(self, config):
    cp = ciscoconfparse.CiscoConfParse(config)
    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))[0]
    hostname = o.re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    self.cfg['hostname'] = hostname
    ports = self._parse_ifaces(cp)
    self.cfg['ports'] = ports
    self.cfg['vlans'] = self._parse_vlans(cp, ports)
    self.cfg['users'] = self._parse_users(cp)

