#!/usr/bin/env python3

import sys
import ciscoconfparse
import yaml
import re
from collections import OrderedDict,defaultdict
import jinja2
import napalm
import logging
import multiprocessing.pool
import traceback

import nak.inventory




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
  CFG_VLAN_RANGE = range(2,4095)

  def __init__(self, configstruct, active_vlans=None):
    self.conf = configstruct
    if active_vlans:
      self.active_vlans = active_vlans
    else:
      self.active_vlans = self.CFG_VLAN_RANGE


  def _hooks(self):
    self.conf['remove_vlans'] = sorted(list((set(self.active_vlans) - set(self.IGNORE_VLANS)) - set([int(v) for v in self.conf['vlans']])))
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
          if (pd['tagged'].lower() == 'all' or pd['tagged'] == '*'):
            if 'untagged' in pd:
              pd['tagged'] = sorted(list(set(self.conf['vlans'].keys()) - {pd['untagged']}))
            else:
              pd['tagged'] = sorted(list(set(self.conf['vlans'].keys())))
          else:
            raise ValueError('Unsupported tagged value:' % pd['tagged'])


  @classmethod
  def _compact_int_list(cls, lst):
    try:
      slst = list(sorted([int(x) for x in lst]))
    except:
      print("Error compacting int list %s" % str(lst))
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
    

def get_gen_object(boxtype):
  t = boxtype.strip().lower()
  if t == 'iosold':
    import nak.ios
    return nak.ios.IOSOldGen
  elif t == 'ios':
    import nak.ios
    return nak.ios.IOSGen
  elif t == 'nxos':
    import nak.ios
    return nak.ios.NXOSGen
  elif t == 'os10' or t == 'dellos10':
    import nak.os10
    return nak.os10.OS10Gen
  else:
    raise ValueError("Unknown box type: %s" % boxtype)


def get_parser_object(boxtype):
  t = boxtype.strip().lower()
  if t == 'ios' or t == 'nxos':
    import nak.ios
    return nak.ios.IOSParser
  elif t == 'procurve':
    import nak.procurve
    return nak.procurve.ProCurveParser
  elif t == 'os10' or t == 'dellos10':
    import nak.os10
    return nak.os10.OS10Parser
  elif t == 'ironware':
    import nak.ironware
    return nak.ironware.IronwareParser
  else:
    raise ValueError("Unknown box type: %s" % boxtype)


class Box(object):
  global_delay_factor = 0.5

  def __init__(self, boxtype):
    self.boxtype = boxtype


  def connect(self, host, user, passwd, enab=None):
    logging.debug("Connecting to host %s with driver %s", host, self.boxtype)
    self.hostname = host
    self.driver = napalm.get_network_driver(self.boxtype)
    if enab:
      self.conn = self.driver(host, username=user, password=passwd, optional_args={"global_delay_factor": self.global_delay_factor, 'secret': enab})
    else:
      self.conn = self.driver(host, username=user, password=passwd, optional_args={"global_delay_factor": self.global_delay_factor})
    self.conn.open()


  def close(self):
    self.conn.close()


  def getRunning(self):
    return self.conn.get_config()['running']


  def configure(self, conf, simulate=False):
    logging.debug("Loading merge candidate for %s (%s)", self.hostname, self.boxtype)
    self.conn.load_merge_candidate(config=conf)
    if simulate:
      logging.debug("Comparing config for %s (%s)", self.hostname, self.boxtype)
      res = self.conn.compare_config()
      logging.debug("Candidate discard for %s (%s)", self.hostname, self.boxtype)
      self.conn.discard_config()
    else:
      logging.debug("Candidate commit for %s (%s)", self.hostname, self.boxtype)
      self.conn.commit_config()
      res = conf

    logging.debug("Configure finished for %s (%s)", self.hostname, self.boxtype)
    return res



class Batch(object):
  MAX_THREADS = 50

  def __init__(self, simulate=False, limit=None, invs=None, vault_pass=None):
    """
      bool simulate
      limit = ['hostname1', 'fqdn2.domain.eu'] or None
      invs = ['/etc/ansible/hosts', ...]
      str vault_pass
    """
    kwargs = {}
    if invs:
      kwargs['sources'] = invs
    if vault_pass:
      kwargs['vault_pass'] = vault_pass
    self.inv = nak.inventory.AnsibleInventoryConfigs(**kwargs)
    self.sim = simulate
    self.lim = limit


  def runAllSerial(self):
    for h,confstruct in self.inv.getHostsWithConfStruct(self.lim):
      print(self.runForHost(h, confstruct))


  def runAllParallel(self):
    def _runForHost(args):
      try:
        self, h, cfs = args
        return self.runForHost(h, cfs)
      except Exception as e:
        return 'Error for %s : %s' % (h['inventory_hostname'], "\n".join(traceback.format_list(traceback.extract_tb(sys.exc_info()[2]))))
    p = multiprocessing.pool.ThreadPool(self.MAX_THREADS)
    report = p.map(_runForHost, [(self, h, cfs) for h, cfs in self.inv.getHostsWithConfStruct(self.lim)])
    for r in report:
      print(r)


  def runForHost(self, h, confstruct):
      ret = ""
      logging.debug("Working on %s" % h['inventory_hostname'])

      go = get_gen_object(h['boxtype'])
      textcfg = go(confstruct).genText()

      b = Box(h['boxtype'])
      if 'ansible_become_password' in h:
        bcmpasswd = h['ansible_become_password']
      else:
        bcmpasswd = None
      logging.debug("Config for %s generated, connecting..." % h['inventory_hostname'])
      b.connect(h['inventory_hostname'], h['ansible_user'], h['ansible_password'], bcmpasswd)
      logging.debug("Connected to %s . Configuration in progress..." % h['inventory_hostname'])
      res = b.configure(textcfg, simulate=self.sim)
      if self.sim:
        ret+=("Config diff for %s:\n" % h['inventory_hostname'])
        ret+=str(res)
        ret+="\n"
      logging.debug("Configuration of %s finished. Closing..." % h['inventory_hostname'])
      b.close()
      ret+="Configuration of %s finished.\n" % h['inventory_hostname']
      logging.debug("Connection to %s closed." % h['inventory_hostname'])
      return ret

