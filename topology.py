#!/usr/bin/env python3
"""
SDN Network Utilization Monitor - Mininet Topology
====================================================
Creates a star topology with one core switch (s1) and four
host-facing switches (s2-s5), each with two hosts attached.

                     [h1]  [h2]
                      |     |
           [h3][h4]--s2----s3--[h5][h6]
                  \\  /       \\  /
                   s1 (core)
                  /  \\       /  \\
           [h7][h8]--s4----s5--[h9][h10]
                      |     |
                     [h9]  [h10]

Simpler linear topology is used for clarity in the demo:

  h1 -- s1 -- s2 -- s3
              |
              h2    h3 (attached to s2, s3)

Actual topology defined below: 3-switch linear chain with 2 hosts per switch.

Usage:
  sudo python3 topology.py [--controller <IP>] [--port <port>]

  Default controller: 127.0.0.1:6633
"""

import argparse
import sys
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI


def build_topology(controller_ip="127.0.0.1", controller_port=6633):
    """
    Topology: 3 switches in a linear chain, 2 hosts per switch.

      h1 ─┐
           s1 ── s2 ── s3
      h2 ─┘      │      │
                h3,h4  h5,h6
    """
    net = Mininet(
        controller=None,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
    )

    # Remote Ryu controller
    info("*** Adding controller\n")
    c0 = net.addController(
        "c0",
        controller=RemoteController,
        ip=controller_ip,
        port=controller_port,
    )

    # Switches
    info("*** Adding switches\n")
    s1 = net.addSwitch("s1", protocols="OpenFlow13")
    s2 = net.addSwitch("s2", protocols="OpenFlow13")
    s3 = net.addSwitch("s3", protocols="OpenFlow13")

    # Hosts — bw=10 Mbps, delay=2ms on each link
    info("*** Adding hosts\n")
    hosts = {}
    for i in range(1, 7):
        hosts[f"h{i}"] = net.addHost(f"h{i}")

    # Host ↔ switch links (10 Mbps access links)
    info("*** Creating host links\n")
    link_opts = dict(bw=10, delay="2ms", loss=0)
    net.addLink(hosts["h1"], s1, **link_opts)
    net.addLink(hosts["h2"], s1, **link_opts)
    net.addLink(hosts["h3"], s2, **link_opts)
    net.addLink(hosts["h4"], s2, **link_opts)
    net.addLink(hosts["h5"], s3, **link_opts)
    net.addLink(hosts["h6"], s3, **link_opts)

    # Switch ↔ switch links (10 Mbps backbone)
    info("*** Creating backbone links\n")
    backbone_opts = dict(bw=10, delay="1ms", loss=0)
    net.addLink(s1, s2, **backbone_opts)
    net.addLink(s2, s3, **backbone_opts)

    return net, c0


def run_tests(net):
    """
    Run two test scenarios automatically:

    Scenario 1 – Connectivity test (all-pairs ping)
    Scenario 2 – Bandwidth measurement (iperf h1 → h5)
    """
    info("\n" + "=" * 60 + "\n")
    info("TEST SCENARIO 1: Connectivity (pingall)\n")
    info("=" * 60 + "\n")
    net.pingAll()

    info("\n" + "=" * 60 + "\n")
    info("TEST SCENARIO 2: Bandwidth (iperf h1 → h5, 10 s)\n")
    info("=" * 60 + "\n")
    h1 = net.get("h1")
    h5 = net.get("h5")
    net.iperf([h1, h5], l4Type="TCP", seconds=10)

    info("\n" + "=" * 60 + "\n")
    info("TEST SCENARIO 3: Bandwidth (iperf h2 → h6, UDP)\n")
    info("=" * 60 + "\n")
    h2 = net.get("h2")
    h6 = net.get("h6")
    net.iperf([h2, h6], l4Type="UDP", seconds=10)


def main():
    parser = argparse.ArgumentParser(description="Network Utilization Monitor Topology")
    parser.add_argument("--controller", default="127.0.0.1", help="Controller IP")
    parser.add_argument("--port", type=int, default=6633, help="Controller port")
    parser.add_argument("--test", action="store_true",
                        help="Run automated tests then drop to CLI")
    args = parser.parse_args()

    setLogLevel("info")

    info("*** Building topology\n")
    net, c0 = build_topology(args.controller, args.port)

    info("*** Starting network\n")
    net.start()

    # Give the controller a moment to install flow rules
    import time
    info("*** Waiting 3 s for controller to initialise...\n")
    time.sleep(3)

    if args.test:
        run_tests(net)

    info("\n*** Dropping into Mininet CLI (type 'exit' to quit)\n")
    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    main()
