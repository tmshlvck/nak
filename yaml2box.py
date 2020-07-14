#!/usr/bin/env python3

import napalm
import click
import jinja2
import yaml


ignore_vlans = [1,1002, 1003, 1004, 1005]


def apply_conf(conf, device, simulate=False):
  device.load_merge_candidate(config=conf)
  print("=== Diff ===")
  print(device.compare_config())
  print("=== End diff ===")
  if simulate:
    device.discard_config()
  else:
    device.commit_config()


def get_configured(vlans):
  confports = set()
  for v in vlans:
    if int(v) in ignore_vlans:
      continue
    confports |= set(vlans[v]['interfaces'])
  return confports
 

def gen_cleanup(config, vlans):
  configured_ports = get_configured(vlans)

  config['remove_vlans'] = []
  for v in [int(k) for k in vlans]:
    if not v in config['vlans'] and not v in ignore_vlans:
      config['remove_vlans'].append(v)

  config['clean_ports'] = []
  for p in config['ports']:
    if not config['ports'][p].get('descr') and config['ports'][p].get('shutdown') and \
      p in configured_ports:
      config['clean_ports'].append(p)

  for p in config['clean_ports']:
    del(config['ports'][p])

  return config


def read_conf(fhs):
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


def gen_text(c, t):
  jenv = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), autoescape=False)
  jenv.globals.update(merge_vlans=merge_vlans)
  t = jenv.get_template('%s.j2' % t)
  return t.render(config=c)




@click.command()
@click.option('-t', '--type', 't', help="cisco|os10")
@click.option('-h', '--host', 'h', help="hostname or IP")
@click.option('-u', '--user', 'u', help="user")
@click.option('-p', '--passwd', 'p', help="password/secret")
@click.option('-e', '--enable', 'enab', help="enable secret")
@click.option('-s', '--simulate', 'sim', help="simulate", is_flag=True)
@click.argument('ymls', type=click.File('r'), nargs=-1)
def main(t, h, u, p, enab, sim, ymls):
  """
  Take YML file, translate it to <type> config and print or  apply it to a box.
  """

  driver = napalm.get_network_driver(t)
  if enab:
    device = driver(h, username=u, password=p, optional_args={"global_delay_factor": 3, 'secret': enab})
  else:
    device = driver(h, username=u, password=p, optional_args={"global_delay_factor": 3})
  device.open()

  conf = read_conf(ymls)
  gen_cleanup(conf, device.get_vlans())
  tc = gen_text(conf, t)
  if sim:
    print("=== Generated config ===")
    print(tc)
    print("=== End generated config ===")
  apply_conf(tc, device, sim)
    
  device.close()
  
if __name__ == '__main__':
  main()

