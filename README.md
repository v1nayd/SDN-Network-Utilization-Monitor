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
network_monitor/
├── controller/
│   └── monitor_controller.py   # Ryu app (L2 learning switch + stats monitor)
├── topology/
│   └── topology.py             # Mininet 3-switch linear topology
├── dashboard/
│   └── index.html              # Browser dashboard (Chart.js, no build step)
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
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```

### Scenario 2 – Bandwidth (TCP iperf)

```
mininet> iperf h1 h5
```

Expected: throughput close to 10 Mbps (link capacity).
Dashboard TX/RX bars for the relevant ports should spike.

### Scenario 3 – Bandwidth (UDP iperf)

```
mininet> h1 iperf -u -c 10.0.0.5 -b 8M -t 15 &
mininet> h5 iperf -u -s &
```

Check flow table changes and packet counters in the dashboard.

### Scenario 4 – Parallel streams

```
mininet> h1 iperf -c 10.0.0.5 -t 20 -P 4 &
mininet> h2 iperf -c 10.0.0.6 -t 20 &
```

Observe aggregate utilization approaching link saturation.

---

## Expected Output

### REST API sample (`/stats/all`)

```json
{
  "1": {
    "1": {
      "port": 1,
      "tx_mbps": 3.421,
      "rx_mbps": 2.985,
      "tx_util_pct": 34.2,
      "rx_util_pct": 29.9,
      "tx_bytes": 1485320,
      "rx_bytes": 1290440,
      "tx_packets": 9870,
      "rx_packets": 8540,
      "tx_errors": 0,
      "rx_errors": 0,
      "timestamp": 1718000000.12
    }
  }
}
```

### Flow table (after pingall)

```
cookie=0x0, duration=12s, table=0, n_packets=24, n_bytes=2016,
  priority=1,in_port=1,dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:05
  actions=output:3

cookie=0x0, duration=60s, table=0, n_packets=0,
  priority=0 actions=CONTROLLER:65535
```

---

## Proof of Execution

Screenshots and Wireshark captures are in `/proof/` on this repo:

- `pingall_output.png` — 0% packet loss across all 6 hosts
- `iperf_tcp.png` — TCP throughput h1→h5 (~9.5 Mbps)
- `iperf_udp.png` — UDP throughput with jitter stats
- `flow_table_s1.png` — `ovs-ofctl dump-flows s1` after learning
- `wireshark_ofp.pcap` — captured OpenFlow messages (SYN, Features, FlowMod, StatsReply)
- `dashboard.png` — live dashboard screenshot

---

## Performance Metrics

| Metric | Observed | Expected |
|--------|----------|----------|
| Ping RTT h1→h5 | ~5 ms | 2+2+1 ms links |
| TCP throughput | ~9.5 Mbps | ≤10 Mbps |
| Stats poll interval | 2 s | configurable |
| Flow rule idle timeout | 30 s | per-flow |
| Controller reaction time | <1 ms | local Mininet |

---

## References

1. Mininet documentation — https://mininet.org
2. Ryu SDN framework — https://ryu-sdn.org
3. OpenFlow 1.3 specification — https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf
4. Open vSwitch documentation — https://docs.openvswitch.org
5. "Software Defined Networks: A Comprehensive Approach" — Goransson & Black, 2014
6. Ryu Book — https://osrg.github.io/ryu-book/en/html/
