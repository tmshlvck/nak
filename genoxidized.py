#!/usr/bin/env python3

import warnings
warnings.simplefilter("ignore")

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


def_inv = 'hosts'

def dbg(msg):
  print(msg, file=sys.stdout)

def get_hosttype(h):
  return nak.batch.AnsibleInventory.get_type(h['group_names'])

@click.command()
@click.option('-l', '--limit', 'lim', help="limit actions to hostnames or shorthostnames", multiple=True)
@click.option('-i', '--inventory', 'inv', help="ansible inventory file (default: %s)" % def_inv, type=click.Path(exists=True), default=def_inv)
@click.option('-p', '--vaultpasswd', 'vault_pass', help="ansible vault password", default=None)
def main(lim, inv, vault_pass):
  """
  Generate CSV source fox Oxidized based on Ansible inventory.
  """
  i = nak.batch.AnsibleInventory()
  if lim:
    limit = lim
  else:
    limit = None
  hosts = i.get_hosts(inv, vault_pass, limit)

  for h in hosts:
#    print(str(h))
    try:
      print("%s:%s:%s:%s" % (h['inventory_hostname'], get_hosttype(h), h['ansible_user'], h['ansible_password']))
    except:
      pass

  return 0 
  
if __name__ == '__main__':
  main()

