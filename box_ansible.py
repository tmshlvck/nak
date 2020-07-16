#!/usr/bin/env python3

import json
from collections import namedtuple
from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager
import click
import nak.box
import sys
import os.path


def dbg(msg):
  print(msg, file=sys.stdout)


def get_hosts(sources=None, vault_pass=None):
  """
  sources: ['hosts',]
  vault_pass: str
  """

  loader = DataLoader()
  if vault_pass:
    loader.set_vault_password(vault_pass)
  if sources:
    inventory = InventoryManager(loader=loader, sources=sources)
  else:
    inventory = InventoryManager(loader=loader)

  variable_manager = VariableManager(loader=loader, inventory=inventory)

  hosts = variable_manager.get_vars()['groups']['all']

  for h in hosts:
    hv = variable_manager.get_vars(host=inventory.get_host(h))
    yield {k:hv[k] for k in ['ansible_user', 'ansible_password', 'ansible_become_password', 'inventory_hostname', 'inventory_hostname_short', 'group_names']}


def get_type(group_names):
  if 'ios' in group_names:
    return 'ios'

  if 'nxos' in group_names:
    return 'nxos'

  if 'dellos10' in group_names:
    return 'dellos10'

  raise Exception('Can not derive type from: %s' % str(group_names))



@click.command()
@click.option('-a', '--apply', 'a', help="apply YAML file from DIR/hostname")
@click.option('-p', '--preamble', 'p', help="apply specific YAML file(s) before dir", multiple=True)
@click.option('-d', '--download', 'd', help="download config files to DIR/hostname")
@click.option('-c', '--convert', 'c', help="convert downloaded config to YAML", is_flag=True)
@click.option('-s', '--simulate', 's', help="simulate", is_flag=True)
@click.option('-v', '--verbose', 'v', help="verbose output", is_flag=True)
@click.option('-i', '--inventory', 'i', help="inventory file")
def main(a, p, d, c, s, v, i):
  """
  Interact with the boxes defined in Ansible inventory. Download config or take YML file, translate
  it to box config and print or apply it to a box.
  """
  global debug
  if v:
    debug = True

  if i:
    hosts = get_hosts(sources=[i])
  else:
    hosts = get_hosts()

  for hostdef in hosts:
    try:
      t = get_type(hostdef['group_names'])
    except:
      dbg('Ignoring host of unknown type %s' % hostdef['inventory_hostname'])
      continue

    dbg('Connecting to a host %s of type %s...' % (hostdef['inventory_hostname'], t))
    boxo = nak.box.get_box_object(t)
    b = boxo()
    b.connect(hostdef['inventory_hostname'], hostdef['ansible_user'], hostdef['ansible_password'], hostdef['ansible_become_password'])

    if d:
      fn = os.path.join(d, '%s_confg' % hostdef['inventory_hostname_short'])
      dbg("Downloading running_config from: %s to file %s" % (hostdef['inventory_hostname'], fn))
      with open(fn, 'w') as fh:
        cont = b.get_running()
        fh.write(cont)
        dbg("Downloaded %d bytes" % len(cont))
      if c:
        cpo = nak.confparse.get_box_object(t)
        o = cpo()
        o.parse_open_file(fn)
        cfn = os.path.join(d, '%s.yml' % hostdef['inventory_hostname_short'])
        dbg("Converting running_config from: %s to file %s" % (hostdef['inventory_hostname'], cfn))
        with open(cfn, 'w') as fh:
          fh.write(o.gen_yaml())
    elif a:
      files = p
      files.append(os.path.join(a, '%s.yml' % hostdef['inventory_hostname_short']))
      dbg("Applying files: %s to host %s" % (str(files), hostdef['inventory_hostname']))
      b.update_config(files, s)
    else:
      print("No action (download|apply) specified.")
      return -1

    b.close()

  return 0 
  
if __name__ == '__main__':
  main()

