#!/usr/bin/env python3

import napalm
import click
import jinja2
import yaml
import nak.confparse

global_delay_factor=0.5

class Box(object):
  IGNORE_VLANS = [1,]

  def __init__(self):
    pass


  def connect(self, host, user, passwd, enab=None):
    self.driver = napalm.get_network_driver(self.NAPALM_DRIVER)
    if enab:
      self.conn = self.driver(host, username=user, password=passwd, optional_args={"global_delay_factor": global_delay_factor, 'secret': enab})
    else:
      self.conn = self.driver(host, username=user, password=passwd, optional_args={"global_delay_factor": global_delay_factor})
    self.conn.open()


  def close(self):
    self.conn.close()


  def get_running(self):
    return self.conn.get_config()['running']


  def get_running_parsed(self):
    cpo = nak.confparse.get_box_object(self.NAPALM_DRIVER)
    liveconf = cpo()
    liveconf.parse_file(self.get_running().splitlines())
    return liveconf


  # New config generate & apply


  @classmethod
  def _gen_text_conf(cls, conf, template_dir='templates'):
    jenv = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir), autoescape=False)
    t = jenv.get_template(cls.TEMPLATE)
    return t.render(config=conf)


  def _process_port(self, portname, config):
    pd = config['ports'][portname]
    if 'tagged' in pd:
      if type(pd['tagged']) is str:
        if pd['tagged'].lower() == 'all' or pd['tagged'] == '*':
          pd['tagged'] = sorted(list(set(config['vlans'].keys()) - {pd['untagged']}))
        else:
          raise ValueError('Unsupported tagged value:' % pd['tagged'])
    return pd


  def _process_config(self, config):
    # abstract to be extended by each flavor
    for p in config['ports']:
      config['ports'][p] = self._process_port(p, config)
    return config


  def _apply_text(self, conf, simulate=False):
    self.conn.load_merge_candidate(config=conf)
    res = self.conn.compare_config()
    if simulate:
      self.conn.discard_config()
    else:
      self.conn.commit_config()
    return res


  def update_config(self, files, sim=False, template_dir='templates'):
    def merge_conf(res, frag):
      for k in frag:
        res[k] = frag[k]

    config = {}
    for yf in files:
        with open(yf, 'r') as fh:
          c = yaml.safe_load(fh)
        merge_conf(config, c)

    config = self._process_config(config)
    textconf = self._gen_text_conf(config, template_dir)
    diff = self._apply_text(textconf, sim)
    return (textconf, diff) # (textconf, diff) 


class IOSBox(Box):
  IGNORE_VLANS = [1,1002, 1003, 1004, 1005]
  TEMPLATE = 'ios.j2'
  NAPALM_DRIVER = 'ios'

  def __init__(self):
    pass


  def _get_configured_ifaces(self):
    confports = set()
    vlans = self.conn.get_vlans()
    for v in vlans:
      if int(v) in self.IGNORE_VLANS:
        continue
      confports |= set(vlans[v]['interfaces'])
    return confports
 

  def _process_config(self, config):
    super()._process_config(config)
    vlans = self.conn.get_vlans()
    configured_ports = self._get_configured_ifaces()

    config['remove_vlans'] = []
    for v in [int(k) for k in vlans]:
      if not v in config['vlans'] and not v in self.IGNORE_VLANS:
        config['remove_vlans'].append(v)

    config['clean_ports'] = []
    for p in config['ports']:
      if not config['ports'][p].get('descr') and config['ports'][p].get('shutdown') and \
        p in configured_ports:
        config['clean_ports'].append(p)

    for p in config['clean_ports']:
      del(config['ports'][p])

    config['clean_users'] = []
    liveconf = self.get_running_parsed()
    for u in liveconf.cfg['users']:
      if not u in config['users']:
        config['clean_users'].append(u)

    return config


  @classmethod
  def _gen_text_conf(cls, conf, template_dir='templates'):
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

    jenv = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir), autoescape=False)
    jenv.globals.update(merge_vlans=merge_vlans)
    t = jenv.get_template(cls.TEMPLATE)
    return t.render(config=conf)




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


  def _process_config(self, config):
    super()._process_config(config)

    liveconf = self.get_running_parsed()
    config['remove_vlans'] = []
    for v in [int(k) for k in liveconf.cfg['vlans']]:
      if not v in config['vlans'] and not v in self.IGNORE_VLANS:
        config['remove_vlans'].append(v)

    config['clean_ports'] = []
    for p in config['ports']:
      if not config['ports'][p].get('descr') and config['ports'][p].get('shutdown') and \
        not config['ports'][p].get('tagged') and config['ports'][p]['untagged'] != 1 and \
        liveconf.is_iface_configured(p):
        config['clean_ports'].append(p)

    for p in config['clean_ports']:
      del(config['ports'][p])

    config['clean_users'] = []
    for u in liveconf.cfg['users']:
      if not u in config['users']:
        config['clean_users'].append(u)

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

