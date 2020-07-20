#!/usr/bin/env python3

import click
import nak.box



@click.command()
@click.option('-t', '--type', 't', help="ios|nxos|dellos10", required=True)
@click.option('-h', '--host', 'h', help="hostname or IP")
@click.option('-u', '--user', 'u', help="user")
@click.option('-p', '--passwd', 'p', help="password/secret")
@click.option('-e', '--enable', 'e', help="enable secret")
@click.option('-d', '--download', 'd', help="download config and save it to file", type=click.Path(exists=False))
@click.option('-a', '--apply', 'a', help="apply YAML files", type=click.Path(exists=True), multiple=True)
@click.option('-s', '--simulate', 's', help="simulate", is_flag=True)
def main(t, h, u, p, e, d, a, s):
  """
  Interact with the box. Download config or take YML file, translate it to <type> config
  and print or apply it to a box.
  """

  boxo = nak.box.get_box_object(t)
  b = boxo()
  b.connect(h, u, p, e)

  if d:
    with open(d, 'w') as fh:
      fh.write((b.get_running()))
  elif a:
    b.update_config(a, s)
  else:
    print("No action (download|apply) specified.")

  b.close()
  
if __name__ == '__main__':
  main()

