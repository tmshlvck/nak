#!/usr/bin/env python3
# coding: utf-8

"""
nak

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


import sys
import ciscoconfparse
import yaml
import re
from collections import OrderedDict,defaultdict
import jinja2
import napalm
import logging
import multiprocessing.pool

import nak.inventory




""" Data Model Example:

---
hostname: bb
ports:
  Port-channel1:
    shutdown: false
    type: trunk
    descr: itchy+scratchy
    untagged: 1
    tagged: all
  Port-channel4:
    shutdown: false
    type: trunk
    descr: ce.switch.ignum.cz
    untagged: 1
    tagged: all
  FastEthernet0:
    clean: true
  GigabitEthernet1/0/1:
    clean: true
  GigabitEthernet1/0/2:
    shutdown: false
    type: trunk
    descr: ubi-b.switch.ignum.cz
    untagged: 9
    tagged:
    - 143
  GigabitEthernet1/0/3:
    shutdown: false
    type: trunk
    descr: a0:E1/1/40
    untagged: 1
    tagged: all
  GigabitEthernet1/0/4:
    shutdown: true
    type: access
    descr: ubi-poe.switch.ignum.cz
    untagged: 9
  GigabitEthernet1/0/5:
    clean: true
...
  GigabitEthernet1/0/26:
    shutdown: false
    type: trunk
    descr: scratchy:e1/1/45:1
    lag: 1
    lagmode: active
  GigabitEthernet1/0/27:
    clean: true
  GigabitEthernet1/0/28:
    clean: true
users:
  th:
  - privilege 15 secret 5 $1$xxX<cut>xXx
"""



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


  def getConfStruct(self):
    return self.cfg


  def genYAML(self):
    yaml.add_representer(OrderedDict, lambda self, data: yaml.representer.SafeRepresenter.represent_dict(self, data.items()))
    return yaml.dump(self.getConfStruct(), sort_keys=False, explicit_start=True)


class BasicGen(object):
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


  @classmethod
  def _normalize_namestr(cls, s):
    if " " in s:
      return '"%s"' % s
    else:
      return s


class Box(object):
  global_delay_factor = 0.5

  def __init__(self, boxtype):
    self.boxtype = boxtype
    self.hostname = 'Not connected'
    self.conn = None


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


def get_box_object(boxtype):
  t = boxtype.strip().lower()
  if t == 'ios':
    import nak.cisco
    return nak.cisco.IOSBox
  elif t == 'nxos':
    import nak.cisco
    return nak.cisco.NXOSBox
  elif t == 'os10' or t == 'dellos10':
    import nak.os10
    return nak.os10.OS10Box
  else:
    raise ValueError("Unknown box type: %s" % boxtype)


def get_parser_object(boxtype):
  t = boxtype.strip().lower()
  if t == 'ios':
    import nak.cisco
    return nak.cisco.IOSParser
  if t == 'nxos':
    import nak.cisco
    return nak.cisco.NXOSParser
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
        return 'Error for %s :\n%s' % (h['inventory_hostname'], logging.traceback.format_exc())
    p = multiprocessing.pool.ThreadPool(self.MAX_THREADS)
    report = p.map(_runForHost, [(self, h, cfs) for h, cfs in self.inv.getHostsWithConfStruct(self.lim)])
    for r in report:
      print(r)


  def runForHost(self, h, confstruct):
      ret = ""
      logging.debug("Working on %s" % h['inventory_hostname'])

      bo = get_box_object(h['boxtype'])
      po = get_parser_object(h['boxtype'])

      b = bo()
      if 'ansible_become_password' in h:
        bcmpasswd = h['ansible_become_password']
      else:
        bcmpasswd = None
      logging.debug("Connecting to %s ." % h['inventory_hostname'])
      b.connect(h['inventory_hostname'], h['ansible_user'], h['ansible_password'], bcmpasswd)
      activeconflines = b.getRunning().splitlines()
      logging.debug("Configuration from %s Downloaded..." % h['inventory_hostname'])
      activeconf = po(activeconflines).getConfStruct()
      logging.debug("Configuration for host %s parsed..." % h['inventory_hostname'])
      textcfg = '\n'.join(b.genSyncAll(confstruct, activeconf))
      logging.debug("Config for %s generated..." % h['inventory_hostname'])
      if textcfg:
        res = b.configure(textcfg, simulate=self.sim)
        if self.sim:
          ret+=("=== Commands for %s ===\n" % h['inventory_hostname'])
          ret+=str(textcfg)
          ret+=("=== End commands for %s ===\n" % h['inventory_hostname'])
          ret+=("\n*** Diff for %s: ***\n" % h['inventory_hostname'])
          ret+=str(res)
          ret+=("\n*** End diff for %s: ***\n" % h['inventory_hostname'])
      else:
        logging.debug("No configuration/changes to execute.")
        if sim:
          ret+=("No changes/config to execute for %s:\n" % h['inventory_hostname'])
      logging.debug("Configuration of %s finished. Closing..." % h['inventory_hostname'])
      b.close()
      ret+="Configuration of %s finished.\n" % h['inventory_hostname']
      logging.debug("Connection to %s closed." % h['inventory_hostname'])
      return ret

