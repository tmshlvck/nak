#!/usr/bin/env python3

import json
from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager
import click
import nak.box
import nak.batch
import sys
import os.path
import yaml


def_config_yaml = '/opt/nak/batch.yml'

def dbg(msg):
  print(msg, file=sys.stdout)


def get_boxconn(hostdef):
  try:
    t = nak.batch.AnsibleInventory.get_type(hostdef['group_names'])
  except:
    dbg('Ignoring host of unknown type %s' % hostdef['inventory_hostname'])
    return None

  dbg('Connecting to a host %s of type %s...' % (hostdef['inventory_hostname'], t))
  boxo = nak.box.get_box_object(t)
  b = boxo()
  b.connect(hostdef['inventory_hostname'], hostdef['ansible_user'], hostdef['ansible_password'], hostdef['ansible_become_password'])
  dbg('Connection established to %s' % (hostdef['inventory_hostname'],))
  return b

def apply_yamls(hostdef, cfg, sim):
  boxc = get_boxconn(hostdef)
  if not boxc:
    return

  files = list(cfg.cfg['prepend_apply_yamls'])
  files.append(os.path.join(cfg.cfg['yaml_config_dir'], '%s.yml' % hostdef['inventory_hostname_short']))
  dbg("Applying files: %s to host %s" % (str(files), hostdef['inventory_hostname']))
  textcfg, diff = boxc.update_config(files, sim)
  if sim:
    dbg("Generated config:\n%s" % textcfg)
    print("Diff:\n%s" % diff)
  boxc.close()

def backup(hostdef, cfg, conv):
  boxc = get_boxconn(hostdef)
  if not boxc:
    return

  fn = os.path.join(cfg.cfg['text_config_dir'], '%s_confg' % hostdef['inventory_hostname_short'])
  dbg("Downloading running_config from: %s to file %s" % (hostdef['inventory_hostname'], fn))
  with open(fn, 'w') as fh:
    cont = boxc.get_running()
    fh.write(cont)
    dbg("Downloaded %d bytes" % len(cont))
  if conv:
    cpo = nak.confparse.get_box_object(t)
    o = cpo()
    o.parse_file(fn)
    cfn = os.path.join(cfg.cfg['yaml_config_dir'], '%s.yml' % hostdef['inventory_hostname_short'])
    dbg("Converting running_config from: %s to file %s" % (hostdef['inventory_hostname'], cfn))
    with open(cfn, 'w') as fh:
      fh.write(o.gen_yaml())

  boxc.close()



@click.command()
@click.option('-a', '--apply', 'a', help="apply YAML files", is_flag=True)
@click.option('-b', '--backup', 'b', help="download text config files", is_flag=True)
@click.option('-c', '--convert', 'c', help="convert downloaded config to YAML", is_flag=True)
@click.option('-s', '--simulate', 's', help="simulate", is_flag=True)
@click.option('-v', '--verbose', 'v', help="verbose output", is_flag=True)
@click.option('-l', '--limit', 'l', help="limit actions to hostnames or shorthostnames", multiple=True)
@click.option('-o', '--config', 'conf', help="configuration file (default: %s)" % def_config_yaml, type=click.Path(exists=True), default=def_config_yaml)
def main(a, b, c, s, v, l, conf):
  """
  Interact with the boxes defined in Ansible inventory. Download config or take YML file, translate
  it to box config and print or apply it to a box.
  """
  global debug
  if v:
    debug = True
    nak.confparse.debug = v
    

  cfg = nak.batch.BatchConfig(conf)

  inv = nak.batch.AnsibleInventory()
  if l:
    limit = l
  else:
    limit = None
  hosts = inv.get_hosts(cfg.cfg['inventories'], cfg.cfg['vault_pass'], limit)

  if a:
    for h in hosts:
      apply_yamls(h, cfg, s)

  elif b:
    for h in hosts:
      backup(h, cfg, c)

  else:
    print("No action specified: -a or -b needed.")

  return 0 
  
if __name__ == '__main__':
  main()

