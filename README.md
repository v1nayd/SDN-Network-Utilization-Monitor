# SDN Network Utilization Monitor
### Orange Problem · Mininet + Ryu + OpenFlow 1.3

A fully functional SDN-based network monitoring solution that:
- Collects per-port **byte and packet counters** from OpenFlow switches via `OFPPortStatsRequest`
- Estimates **bandwidth utilization** (Mbps & % of link capacity) from delta counters
- Exposes metrics as a **REST JSON API** from the Ryu controller
- Displays a **live browser dashboard** that auto-polls every 2 seconds

---

## Repository Structure

```
SDN-Network-Utilization-Monitor/
├── monitor_controller.py   # Ryu app (L2 learning switch + stats monitor)
├── topology.py             # Mininet 3-switch linear topology
├── index.html              # Browser dashboard (Chart.js, no build step)
├── _pycache_
├── Outputs
└── README.md
```

---

## Problem Statement

Measure and display bandwidth utilization across an SDN network built in Mininet.
The controller periodically queries each switch for port statistics, computes
instantaneous throughput from byte-count deltas, and makes that data available
for visualization.

---

## Architecture

```
  [h1,h2] -- s1 -- s2 -- s3 -- [h5,h6]
                   |
               [h3,h4]

  Ryu controller (RemoteController) ←→ all switches via OpenFlow 1.3

  Controller REST API  →  Browser Dashboard
  http://127.0.0.1:8080/stats/all
```

**Flow rule logic**

| Priority | Match | Action | Purpose |
|----------|-------|--------|---------|
| 0 | `*` (table-miss) | `CONTROLLER` | Trigger `packet_in` for unknown MACs |
| 1 | `in_port + eth_src + eth_dst` | `OUTPUT(port)` | Unicast after MAC is learned |

**Bandwidth formula**

```
Δbytes = current_tx_bytes − previous_tx_bytes
Δt     = current_timestamp − previous_timestamp
Mbps   = (Δbytes × 8) / (Δt × 1,000,000)
% util = Mbps / link_capacity_Mbps × 100
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.8 |
| Mininet | ≥ 2.3 |
| Ryu SDN Framework | ≥ 4.34 |
| Open vSwitch | ≥ 2.13 |
| iperf | any |

Install Ryu:
```bash
pip install ryu
```

---

## Setup & Execution

### 1 · Start the Ryu controller (Terminal 1)

```bash
ryu-manager --observe-links controller/monitor_controller.py
```

The controller listens on **TCP 6633** (OpenFlow) and **TCP 8080** (REST API).

Expected output:
```
loading app controller/monitor_controller.py
instantiating app controller/monitor_controller.py of NetworkUtilizationMonitor
BRICK NetworkUtilizationMonitor
  CONSUMES EventOFPSwitchFeatures
  CONSUMES EventOFPPacketIn
  CONSUMES EventOFPPortStatsReply
```

### 2 · Start the Mininet topology (Terminal 2)

```bash
sudo python3 topology/topology.py
```

Add `--test` to run automated ping + iperf tests before dropping into the CLI:
```bash
sudo python3 topology/topology.py --test
```

### 3 · Open the dashboard

Simply open `dashboard/index.html` in a browser:
```bash
xdg-open dashboard/index.html        # Linux
open dashboard/index.html            # macOS
```

Or serve it locally (avoids CORS issues with some browsers):
```bash
cd dashboard && python3 -m http.server 9000
# then visit http://localhost:9000
```

Point the dashboard at `http://127.0.0.1:8080/stats/all`.

---

## Test Scenarios

### Scenario 1 – Connectivity & flow rule installation

Inside the Mininet CLI:
```
mininet> pingall
```

Expected: 0% packet loss.
Observe flow tables:
```bash
sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

### Scenario 2 – Bandwidth Measurement (iperf)

```
mininet> h1 iperf -s &
mininet> h3 iperf -s &
mininet> h5 iperf -s &
mininet> h2 iperf -c 10.0.0.1 -t 3600 &
mininet> h4 iperf -c 10.0.0.3 -t 3600 &
mininet> h6 iperf -c 10.0.0.5 -t 3600 &

```

Expected: throughput close to 10 Mbps (link capacity).
Dashboard TX/RX bars for the relevant ports should spike.

---

## Proof of Execution

Screenshots are in `/Outputs/` on this repo:

- `Mininet Topology Running.png` — Building topology and Adding controller, switches, hosts
- `Pingall Results.png` — 0% dropped across all 6 hosts
- `Flow table.png` — `ovs-ofctl dump-flows s1 & s2` Confirmation of unicast rules alonside permanent table-miss rule
- `Iperf Running.png` — Mininet CLI after starting all six iperf commands
- `REST API curl Response.png` — JSON response with non-zero tx_mbps and rx_mbps values while iperf is running
- `Dashboard 1.png` `Dashboard 2.png`— Live dashboard screenshot
- `Latency 1.png` `Latency 2.png` — Results between two host pairs with different path lengths
---

## Performance Metrics

| Host Pair | Path              | Configured Delays          | Expected RTT | Observed RTT                      | Status   |
|-----------|-------------------|----------------------------|--------------|-----------------------------------|----------|
| H3 → H5   | H3–S2–S1–S3–H5   | H→S: 2ms × 4, S→S: 1ms × 2 | ~20 ms       | avg 218.4 ms (min 209 / max 233)  | +198 ms  |
| H1 → H2   | H1–S1–H2          | H→S: 2ms × 2, S→S: 0ms    | ~8 ms        | avg 2187.1 ms (min 1827 / max 2619) | +2179 ms |
| H1–H6 (all) | Various via S1–S3 | Backbone: 1ms, Host: 2ms  | 8–20 ms      | 0% packet loss                    | reachable |
---

