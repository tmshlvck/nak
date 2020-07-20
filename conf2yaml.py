#!/usr/bin/env python3


import sys
import yaml
import click
import nak.confparse


@click.command()
@click.option('-t', '--type', 't', help="cisco|procurve|os10|brocade")
@click.option('-d', '--debug', 'debugparam')
@click.argument('files', nargs=-1, type=click.File('r'))
def main(t, debugparam, files):
  nak.confparse.debug = debugparam

  cpo = nak.confparse.get_box_object(t)
  for f in files:
    o = cpo()
    o.parse_file(f.readlines())
    print(o.gen_yaml())
 

if __name__ == '__main__':
  main()

