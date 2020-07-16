#!/usr/bin/env python3

import napalm
import click
import jinja2
import yaml
import nak.confparse


class Box(object):
  IGNORE_VLANS = [1,]

  def __init__(self):
    pass


  def connect(self, host, user, passwd, enab=None):
    self.driver = napalm.get_network_driver(self.NAPALM_DRIVER)
    if enab:
      self.conn = self.driver(host, username=user, password=passw, optional_args={"global_delay_factor": 3, 'secret': enab})
    else:
      self.conn = self.driver(host, username=user, password=passwd, optional_args={"global_delay_factor": 3})
    self.conn.open()


  def _apply_text(self, conf, simulate=False):
    self.conn.load_merge_candidate(config=conf)
    res = self.conn.compare_config()
    if simulate:
      self.conn.discard_config()
    else:
      self.conn.commit_config()
    return res


  def _cleanup_config(self, config):
    return config


  @classmethod
  def _read_ymls(cls, fhs):
    def merge_conf(res, frag, hostname=None):
      for swname in frag:
        if swname == 'all' or not hostname or swname == hostname:
          for k in frag[swname]:
            res[k] = frag[swname][k]

    config = {}
    for fh in fhs:
      c = yaml.safe_load(fh)
      merge_conf(config, c)

    return config


  @classmethod
  def _gen_text_conf(cls, conf):
    def merge_vlans(a,b):
      res = []
      if type(a) is list:
        res += a
      else:
        res.append(a)
      if type(b) is list:
        res += b
      else:
        res.append(b)
      return sorted(res)

    jenv = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), autoescape=False)
    jenv.globals.update(merge_vlans=merge_vlans)
    t = jenv.get_template(cls.TEMPLATE)
    return t.render(config=conf)


  def close(self):
    self.conn.close()


  def get_running(self):
    return self.conn.get_config()['running']


  def update_config(self, ymls, sim=False):
    conf = self._read_ymls(ymls)
    self._cleanup_config(conf)
    tc = self._gen_text_conf(conf)
    diff = self._apply_text(tc, sim)
    if sim:
      print("=== Generated config ===")
      print(tc)
      print("=== DIFF ===")
      print(diff)


class IOSBox(Box):
  IGNORE_VLANS = [1,1002, 1003, 1004, 1005]
  TEMPLATE = 'ios.j2'
  NAPALM_DRIVER = 'ios'

  def __init__(self):
    pass


  def _get_configured_ifaces(self):
    confports = set()
    for v in self.conn.get_vlans():
      if int(v) in IGNORE_VLANS:
        continue
      confports |= set(vlans[v]['interfaces'])
    return confports
 

  def _cleanup_config(self, config):
    vlans = self.conn.get_vlans()
    configured_ports = self._get_configured_ifaces()

    config['remove_vlans'] = []
    for v in [int(k) for k in vlans]:
      if not v in config['vlans'] and not v in cls.IGNORE_VLANS:
        config['remove_vlans'].append(v)

    config['clean_ports'] = []
    for p in config['ports']:
      if not config['ports'][p].get('descr') and config['ports'][p].get('shutdown') and \
        p in configured_ports:
        config['clean_ports'].append(p)

    for p in config['clean_ports']:
      del(config['ports'][p])

    return config




class NXOSBox(IOSBox):
  TEMPLATE = 'nxos.j2'
  NAPALM_DRIVER = 'nxos'

  def __init__(self):
    pass


class OS10Box(Box):
  IGNORE_VLANS = [1,]
  TEMPLATE = 'dellos10.j2'
  NAPALM_DRIVER = 'dellos10'

  def __init__(self):
    pass


  def _cleanup_config(self, config):
    liveconf = nak.confparse.OS10Conf()
    liveconf.parse_file(self.get_running().splitlines())

    config['remove_vlans'] = []
    for v in [int(k) for k in liveconf.get_conf()['vlans']]:
      if not v in config['vlans'] and not v in cls.IGNORE_VLANS:
        config['remove_vlans'].append(v)

    config['clean_ports'] = []
    for p in config['ports']:
      if not config['ports'][p].get('descr') and config['ports'][p].get('shutdown') and \
        not config['ports'][p].get('tagged') and config['ports'][p]['untagged'] != 1 and \
        liveconf.is_iface_configured(p):
        config['clean_ports'].append(p)

    for p in config['clean_ports']:
      del(config['ports'][p])

    return config


def get_box_object(boxtype):
  t = boxtype.strip().lower()
  if t == 'ios':
    return IOSBox
  elif t == 'nxos':
    return NXOSBox
  elif t == 'dellos10':
    return OS10Box
  else:
    raise ValueError("Unknown box type: %s" % boxtype)


