#!/usr/bin/env python3

import yaml
import click
import nak.boxconf


def get_boxconf_object(boxtype):
  t = boxtype.strip().lower()
  if t == 'cisco' or t == 'ios' or t == 'nxos':
    return nak.boxconf.CiscoConf
  elif t == 'procurve':
    return nak.boxconf.ProCurveConf
  elif t == 'os10' or t == 'dellos10':
    return nak.boxconf.OS10Conf
  elif t == 'brocade':
    return nak.boxconf.BrocadeConf
  else:
    raise ValueError("Unknown box type: %s" % boxtype)


@click.command()
@click.option('-t', '--type', 't', help="ios|nxos|procurve|os10|brocade", required=True)
@click.option('-d', '--debug', 'debugparam')
@click.argument('files', nargs=-1, type=click.File('r'))
def main(t, debugparam, files):
  nak.boxconf.debug = debugparam

  cpo = get_boxconf_object(t)
  for f in files:
    o = cpo()
    o.parse_file(f.readlines())
    print(o.gen_yaml())
 

if __name__ == '__main__':
  main()

