#!/usr/bin/env python3

import napalm
import click
import jinja2
import yaml


def applyconf(boxtype, conf, host, user, passwd, secret=None):
  driver = napalm.get_network_driver(boxtype)
  if secret:
    device = driver(host, username=user, password=passwd, optional_args={"global_delay_factor": 3, 'secret': secret})
  else:
    device = driver(host, username=user, password=passwd, optional_args={"global_delay_factor": 3})
    #device = driver(host, user, passwd)
  device.open()
  print("============================")
  print("get_config():")
  print(str(device.get_config()))
  print("============================")
  print("get_facts():")
  print(str(device.get_facts()))
  print("============================")

  print("compare_config():")
  device.load_merge_candidate(config=conf)
  print(device.compare_config())
  print("============================")
  device.discard_config()
  #device.commit_config()

  device.close()
  print("close() finished")


#def confgen(t, yml):
def confgen(t, fh):
#  with open(yml, 'r') as fh:
  config = yaml.safe_load(fh)
    
  jenv = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), autoescape=False)
  # funkce jenv.globals.update(community_fmt=community_fmt)
  t = jenv.get_template('%s.j2' % t)
  return t.render(config=config)




@click.command()
@click.option('-t', '--type', 't', help="cisco|os10")
@click.option('-h', '--host', 'h', help="hostname or IP")
@click.option('-u', '--user', 'u', help="user")
@click.option('-p', '--passwd', 'p', help="password/secret")
@click.option('-e', '--enable', 'enab', help="enable secret")
@click.argument('yml', type=click.File('r'), nargs=1)
def main(t, h, u, p, enab, yml):
  """
  Take YML file, translate it to <type> config and print or  apply it to a box.
  """
  c = confgen(t, yml)
  print(c)
  applyconf(t, c, h, u, p, enab)
    
  
  
if __name__ == '__main__':
  main()

