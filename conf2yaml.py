#!/usr/bin/env python3

# read: https://codingnetworker.com/2016/06/parse-cisco-ios-configuration-ciscoconfparse/


import sys
import ciscoconfparse
import yaml
import re
from collections import OrderedDict,defaultdict
import click

def d(msg):
  #pass
  print(msg, file=sys.stdout)





# Data Model:
# ---
# bb:
#   hostname: bb.switch.ignum.cz
#   vlans:
#     - vlan: 1
#       name: default
#     - vlan: 10
#       name: VMs
#   ports:
#     - port: Ethernet1/1
#       descr: Customer Server 1 (eth0)
#       type: trunk
#       untagged: 1
#       tagged: 1,10
#       shutdown: true
#     - port: Ethernet1/2
#       descr: Customer Server 2 (eth0)
#       type: access
#       untagged: 1
#       shutdown: false
#     - port: Ethernet1/2
#       descr: Customer Server 2 (eth0)
#       type: access
#       untagged: 1
#       shutdown: false
#     - port: PortChannel1
#       descr: Customer Server 3
#       type: trunk
#       untagged: 1
#       shutdown: false
#       mlag: 1




class BasicConf(object):
  def __init__(self, config):
    """ config - list of config lines or str with filename
    """

    raise ValueError("Can not create instance of base class.")


  @classmethod
  def normalize_simple_value(cls, v):
    v = v.strip()

    try:
      return int(v)
    except:
      pass

    return v


  @classmethod
  def normalize_list(cls, v):   
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
        nv = cls.normalize_list(e)
        if type(nv) is list:
          r += nv
        else:
          r.append(nv)
      return r

    if type(v) is list:
      return v
    else:
      return [v]


  def gen_yaml(self):
    yaml.add_representer(OrderedDict, lambda self, data: yaml.representer.SafeRepresenter.represent_dict(self, data.items()))
    return yaml.dump(self.cfg, sort_keys=False, explicit_start=True)




class CiscoConf(BasicConf):
  def __init__(self, conf):
    self.cfg = OrderedDict()
    self.parse_file(conf)
    pass

  @classmethod
  def iface_filter(cls, ifname, iface):
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
  def parse_ifaces(cls, cp, active_vlans):
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

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] = self.normalize_list(m)
          continue

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan add\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] += self.normalize_list(m)
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
 
        d("Ignored: %s" % (c.text))

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

      i.pop('access_vlan', None)
      i.pop('native_vlan', None)
      i.pop('allowed_vlan', None)

      if 'lag' in i:
        i.pop('untagged', None)
        i.pop('tagged', None)

      if 'no-switchport' in i:
        to_remove.append(ifname)

      if not cls.iface_filter(ifname, i):
        to_remove.append(ifname)

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces

  @classmethod
  def parse_vlans(cls, cp):
    vlans = OrderedDict()
    
    for o in cp.find_objects(r"^\s*vlan\s+([0-9,-]+)"):
      vids = o.re_match_typed(r"^\s*vlan\s+([0-9,-]+)\s*$").strip()
      if not vids:
        raise Exception("Wrong vlan: %s" % str(o))

      for vids in cls.normalize_list(vids):
        vid = int(vids)

        if not vid in vlans:
          vlans[vid] = OrderedDict()

        for c in o.children:
          m = c.re_match_typed(r"^\s*name\s+(.+)$", result_type=str)
          if m:
            vlans[vid]['name'] = m
            continue
        
          d("Ignored: %s" % (c.text))

    return vlans


  @classmethod
  def get_shortname(cls, name):
    return name.split('.')[0]

  def parse_file(self, conffile):
    cp = ciscoconfparse.CiscoConfParse(conffile)
    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))[0]
    hostname = o.re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    shorthostname = self.get_shortname(hostname)
    self.cfg[shorthostname] = OrderedDict()
    self.cfg[shorthostname]['hostname'] = hostname
    vlans = self.parse_vlans(cp)
    self.cfg[shorthostname]['vlans'] = vlans
    self.cfg[shorthostname]['ports'] = self.parse_ifaces(cp, vlans)

##################################################################################

class ProCurveConf(BasicConf):
  def __init__(self, conf):
    self.cfg = OrderedDict()
    self.parse_file(conf)
    pass

  @classmethod
  def iface_filter(cls, ifname, iface):
    return True
  

  @classmethod
  def parse_ifaces(cls, cp):
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
        for name in cls.normalize_list(mi.group(1)):
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
      if not cls.iface_filter(ifname, ifaces[ifname]):
        to_remove.append(ifname)

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces

  @classmethod
  def parse_vlans(cls, cp, ifaces):
    vlans = OrderedDict()
    
    for o in cp.find_objects(r"^\s*vlan\s+([0-9,-]+)"):
      vidstr = o.re_match_typed(r"^\s*vlan\s+([0-9,-]+)\s*$").strip()
      if not vidstr:
        raise Exception("Wrong vlan: %s" % str(o))

      for vidstr in cls.normalize_list(vidstr):
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
            for t in cls.normalize_list(m):
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
            for t in cls.normalize_list(m):
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

    return vlans

  @classmethod
  def get_shortname(cls, name):
    return name.split('.')[0]

  def parse_file(self, conffile):
    cp = ciscoconfparse.CiscoConfParse(conffile)
    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))[0]
    hostname = o.re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    shorthostname = self.get_shortname(hostname)
    self.cfg[shorthostname] = OrderedDict()
    self.cfg[shorthostname]['hostname'] = hostname
    ports = self.parse_ifaces(cp)
    self.cfg[shorthostname]['ports'] = ports
    self.cfg[shorthostname]['vlans'] = self.parse_vlans(cp, ports)


##################################################################################

class BrocadeConf(BasicConf):
  def __init__(self, conf):
    self.cfg = OrderedDict()
    self.parse_file(conf)
    pass

  @classmethod
  def iface_filter(cls, ifname, iface):
    if 'ethernet' in ifname:
      return True

    if 'lag' in ifname:
      return True

    return False
  
  @classmethod
  def ifindex_range(cls, start, end):
    ms = re.match(r'^\s*([0-9/]+/)([0-9]+)\s*$', start)
    me = re.match(r'^\s*([0-9/]+/)([0-9]+)\s*$', end)
    if ms and me and ms.group(1) == me.group(1):
      s = int(ms.group(2))
      e = int(me.group(2))
      return ['%s%d' % (ms.group(1), i) for i in range(s,e+1)]

  @classmethod
  def normalize_iflist(cls, rng):
    if not rng.strip():
      return

    m = re.match(r'^\s*(ethe|ethernet)\s+([0-9/]+)\s+to\s+([0-9/]+)(\s+.*)?$', rng)
    if m:
      for i in cls.ifindex_range(m.group(2), m.group(3)):
        yield 'ethernet_%s' % i
      rest = m.group(4)
      if rest:
        for r in cls.normalize_iflist(rest):
          yield r
      return

    m = re.match(r'^\s*(ethe|ethernet)\s+([0-9/]+)(\s.*)?$', rng)
    if m:
      yield 'ethernet_%s' % m.group(2)
      rest = m.group(3)
      if rest:
        for r in cls.normalize_iflist(rest):
          yield r
      return

    raise ValueError("Unknown interface: %s" % str(rng))


  @classmethod
  def parse_ifaces(cls, cp):
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
  def cleanup_ifaces(cls, ifaces):
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

    # remove virtual ifaces
    to_remove = []
    for ifname in ifaces:
      if not cls.iface_filter(ifname, ifaces[ifname]):
        to_remove.append(ifname)

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces


  @classmethod
  def parse_vlans(cls, cp, ifaces):
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
        n = m.group(3).strip()
        if n:
           vlans[vid]['name'] = m.group(3).strip()
      else:
        raise ValueError(str(o))

      for c in o.children:
        m = c.re_match_typed(r'^\s*tagged\s+(.*)$').strip()
        if m:
          for t in cls.normalize_iflist(m):
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
          for t in cls.normalize_iflist(m):
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
  def parse_trunks(cls, cp, ifaces):
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
          for ifname in cls.normalize_iflist(m):
            if not ifname in ifaces:
              ifaces[ifname] = OrderedDict()

            if not 'shutdown' in ifaces[ifname]:
              ifaces[ifname]['shutdown'] = False
            ifaces[ifname]['lag'] = trkname
            ifaces[ifname]['lagmode'] = lagmode

            ifaces[ifname].pop('tagged', None)
            ifaces[ifname].pop('untagged', None)


  @classmethod
  def get_shortname(cls, name):
    return name.split('.')[0]


  def parse_file(self, conffile):
    cp = ciscoconfparse.CiscoConfParse(conffile)
    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))[0]
    hostname = o.re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    shorthostname = self.get_shortname(hostname)
    self.cfg[shorthostname] = OrderedDict()
    self.cfg[shorthostname]['hostname'] = hostname
    ports = self.parse_ifaces(cp)
    self.cfg[shorthostname]['vlans'] = self.parse_vlans(cp, ports)
    self.parse_trunks(cp, ports)
    self.cfg[shorthostname]['ports'] = self.cleanup_ifaces(ports)

#################


class OS10Conf(BasicConf):
  def __init__(self, conf):
    self.cfg = OrderedDict()
    self.parse_file(conf)
    pass

  @classmethod
  def iface_filter(cls, ifname, iface):
    if 'management' in ifname:
      return False

    if 'Vlan' in ifname:
      return False


    return True
  

  @classmethod
  def parse_ifaces(cls, cp, active_vlans):
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

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] = cls.normalize_list(m)
          continue

        m = c.re_match_typed(r"^\s*switchport trunk allowed vlan add\s+(.+)$")
        if m:
          ifaces[name]['allowed_vlan'] += self.normalize_list(m)
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
 
        m = c.re_match_typed(r'^\s*vlt-port-channel\s+(.*)\s*$')
        if m:
          ifaces[name]['mlag'] = int(m)

        m = c.re_match_typed(r'^\s*mtu\s+([0-9]+)\s*$')
        if m:
          ifaces[name]['mtu'] = int(m)-22 # OS10 has WEIRD MTU computation - they count the Eth header including 802.1Q tag and the CRC trailer, all sums up to 22 bytes more than what Cisco/others call MTUa (= L3 datagram size)
        
        d("Ignored: %s" % (c.text))

    to_remove = []
    for ifname in ifaces:
      i = ifaces[ifname]
      if not 'type' in i:
        i['type'] = 'access'
      i['untagged'] = (i['access_vlan'] if 'access_vlan' in i else 1)
      if 'allowed_vlan' in i:
        i['tagged'] = sorted(list(set(i['allowed_vlan']) - {i['untagged']}))

      i.pop('access_vlan', None)
      i.pop('allowed_vlan', None)

      if 'lag' in i:
        i.pop('untagged', None)
        i.pop('tagged', None)

      if 'no-switchport' in i and not 'lag' in i: # remove L2 and MLAG discovery ports but not MLAG downlinks
        to_remove.append(ifname)

      i.pop('no-switchport', None)

      if not cls.iface_filter(ifname, i):
        to_remove.append(ifname)

    for rif in to_remove:
      ifaces.pop(rif, None)

    return ifaces

  @classmethod
  def parse_vlans(cls, cp):
    vlans = OrderedDict()
 
    for o in cp.find_objects(r"^\s*interface"):
      vids = o.re_match_typed(r"^\s*interface Vlan([0-9]+)\s*$").strip()
      if vids:
        vid = int(vids)

        if not vid in vlans:
          vlans[vid] = OrderedDict()

        for c in o.children:
          m = c.re_match_typed(r"^\s*description\s+(.+)$", result_type=str)
          if m:
            vlans[vid]['name'] = m
            continue
        
        d("Ignored: %s" % (c.text))

    return vlans


  @classmethod
  def get_shortname(cls, name):
    return name.split('.')[0]

  def parse_file(self, conffile):
    cp = ciscoconfparse.CiscoConfParse(conffile)
    o = list(cp.find_objects(r"^\s*hostname\s+(.+)$"))[0]
    hostname = o.re_match_typed(r"^\s*hostname\s+(.+)$").strip()
    shorthostname = self.get_shortname(hostname)
    self.cfg[shorthostname] = OrderedDict()
    self.cfg[shorthostname]['hostname'] = hostname
    vlans = self.parse_vlans(cp)
    self.cfg[shorthostname]['vlans'] = vlans
    self.cfg[shorthostname]['ports'] = self.parse_ifaces(cp, vlans)



@click.command()
@click.option('-t', '--type', 't', help="cisco|procurve|os10|")
@click.argument('files', nargs=-1)
def main(t, files):
  for f in files:
    if t == 'cisco':
      o = CiscoConf(f)
    elif t == 'procurve':
      o = ProCurveConf(f)
    elif t == 'os10':
      o = OS10Conf(f)
    elif t == 'brocade':
      o = BrocadeConf(f)
    else:
      raise Exception("Unknown type")

    print(o.gen_yaml())
 

if __name__ == '__main__':
  main()

