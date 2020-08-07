#!/usr/bin/env python3

import sys
import ciscoconfparse
import yaml
import re
from collections import OrderedDict,defaultdict
import jinja2

debug=False

def d(msg):
  if debug:
    print(msg, file=sys.stdout)



# Data Model:
# ---
# hostname: bb.switch.ignum.cz
# vlans:
#   1:
#     name: default
#   10:
#     name: VMs
# ports:
#   Ethernet1/1:
#     descr: Customer Server 1 (eth0)
#     type: trunk
#     untagged: 1
#     tagged: 1,10
#     shutdown: true
#   Ethernet1/2:
#     descr: Customer Server 2 (eth0)
#     type: access
#     untagged: 1
#     shutdown: false
#   Ethernet1/2:
#     descr: Customer Server 2 (eth0)
#     type: access
#     untagged: 1
#     shutdown: false
#   PortChannel1:
#     descr: Customer Server 3
#     type: trunk
#     untagged: 1
#     shutdown: false
#     mlag: 1




class BasicParser(object):
  def __init__(self, config):
    """ config - list of config lines or str with filename
    """
    self.cfg = OrderedDict() # to be done the same in the descendants
    raise ValueError("Can not create instance of base class.")
  

  def parseConfig(self, conffile):
    """
    conffile - str=filename, list(str,...)=list of config file lines
    """
    raise Exception("Not implemented in abstract class")


  def genYAML(self):
    yaml.add_representer(OrderedDict, lambda self, data: yaml.representer.SafeRepresenter.represent_dict(self, data.items()))
    return yaml.dump(self.cfg, sort_keys=False, explicit_start=True)



class BasicGen(object):
  IGNORE_VLANS = [1,]


  def __init__(self, configstruct):
    self.conf = configstruct


  def _hooks(self):
    self.conf['remove_vlans'] = sorted(list((set(range(1,4094)) - set(self.IGNORE_VLANS)) - set([int(v) for v in self.conf['vlans']])))
    self._expand_port_tagged()


  def genText(self):
    self._hooks()
    jenv = jinja2.Environment(loader=jinja2.PackageLoader('nak', 'templates'), autoescape=False)
    t = jenv.get_template(self.TEMPLATE)
    return t.render(config=self.conf)


  def _expand_port_tagged(self):
    for p in self.conf['ports']:
      pd = self.conf['ports'][p]
      if 'tagged' in pd:
        if type(pd['tagged']) is str:
          if pd['tagged'].lower() == 'all' or pd['tagged'] == '*':
            pd['tagged'] = sorted(list(set(self.conf['vlans'].keys()) - {pd['untagged']}))
          else:
            raise ValueError('Unsupported tagged value:' % pd['tagged'])


  @classmethod
  def _compact_int_list(cls, lst):
    try:
      slst = list(sorted([int(x) for x in lst]))
    except:
      print("Error in %s" % str(lst))
      raise
    s = slst[0]
    l = slst[0]
    for x in slst[1:]:
      if x == l+1:
        l = x
      else:
        if s == l:
          yield s
        else:
          yield '%d-%d' % (s, l)
        s = x
        l = x
    if s == l:
      yield s
    else:
      yield '%d-%d' % (s, l)
    

  
