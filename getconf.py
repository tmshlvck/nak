#!/usr/bin/env python3

import napalm
import click


def getconf(t, host, user, passwd, enabsecret=None):
  driver = napalm.get_network_driver(t)
  if enabsecret:
    device = driver(host, user, passwd, optional_args={'secret': enabsecret})
  else:
    device = driver(host, user, passwd)
  device.open()
  c = device.get_config()
  device.close()
  return c['running']

@click.command()
@click.option('-t', '--type', 't', help="ios|nxos|os10|procurve|brocade")
@click.option('-h', '--host', 'h', help="hostname or IP")
@click.option('-u', '--user', 'u', help="user")
@click.option('-p', '--passwd', 'p', help="password/secret")
@click.option('-e', '--enable', 'enab', help="enable secret", default=None)
def main(t, h, u, p, enab):
  print(getconf(t, h, u, p, enab))


if __name__ == '__main__':
  main()

