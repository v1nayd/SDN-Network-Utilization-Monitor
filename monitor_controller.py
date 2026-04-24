"""
SDN Network Utilization Monitor - Ryu Controller
=================================================
Collects byte/packet counters from OpenFlow switches periodically,
estimates per-port bandwidth utilization, and exposes metrics via
a simple REST API for the dashboard.

Assignment: Orange Problem - Network Utilization Monitor
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
import json
import time
from collections import defaultdict

# ── REST API support ───────────────────────────────────────────────
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response

MONITOR_INSTANCE_NAME = "monitor_api_app"
REST_URL = "/stats/{dpid}"
LINK_CAPACITY_MBPS = 10          # simulated link capacity in Mininet


class NetworkUtilizationMonitor(app_manager.RyuApp):
    """
    Main Ryu application.
    
    Responsibilities:
      1. Install a table-miss flow rule so all unknown packets go to controller.
      2. Learn MAC → port mappings (simple L2 learning switch).
      3. Poll every switch for port statistics every POLL_INTERVAL seconds.
      4. Compute bandwidth = Δbytes / Δtime, store in shared dict for REST API.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    POLL_INTERVAL = 2            # seconds between statistics requests

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # MAC learning table:  dpid → { mac: port }
        self.mac_to_port = {}

        # Previous byte counts:  (dpid, port_no) → (tx_bytes, rx_bytes, timestamp)
        self._prev_stats = {}

        # Current utilisation results shared with REST handler
        # Structure: { dpid: { port_no: { tx_mbps, rx_mbps, tx_bytes_total,
        #                                  rx_bytes_total, tx_util_pct, rx_util_pct } } }
        self.port_stats = defaultdict(dict)

        # All known datapaths (switches)
        self.datapaths = {}

        # Register REST controller
        wsgi = kwargs["wsgi"]
        wsgi.register(StatsController,
                      {MONITOR_INSTANCE_NAME: self})

        # Start background polling thread
        self._monitor_thread = hub.spawn(self._monitor_loop)

    # ── OpenFlow event handlers ────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Called when a switch connects. Install table-miss flow entry."""
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        self.datapaths[datapath.id] = datapath
        self.logger.info("Switch connected: dpid=%016x", datapath.id)

        # Table-miss: match everything, send to controller (lowest priority)
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handle unknown packets:
          - Learn source MAC → in_port.
          - Flood if destination unknown; otherwise install a unicast flow.
        """
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return                          # ignore LLDP

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port   # learn

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install a flow rule to avoid future controller involvement
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self._add_flow(datapath, priority=1, match=match,
                           actions=actions, idle_timeout=30, hard_timeout=120)

        # Send the buffered packet out
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Process port statistics reply from a switch."""
        now      = time.time()
        datapath = ev.msg.datapath
        dpid     = datapath.id

        for stat in ev.msg.body:
            pno     = stat.port_no
            tx_b    = stat.tx_bytes
            rx_b    = stat.rx_bytes
            tx_pk   = stat.tx_packets
            rx_pk   = stat.rx_packets
            tx_err  = stat.tx_errors
            rx_err  = stat.rx_errors
            key     = (dpid, pno)

            # Compute bandwidth from delta
            tx_mbps = rx_mbps = 0.0
            if key in self._prev_stats:
                prev_tx, prev_rx, prev_t = self._prev_stats[key]
                dt = now - prev_t
                if dt > 0:
                    tx_mbps = ((tx_b - prev_tx) * 8) / (dt * 1_000_000)
                    rx_mbps = ((rx_b - prev_rx) * 8) / (dt * 1_000_000)

            self._prev_stats[key] = (tx_b, rx_b, now)

            self.port_stats[dpid][pno] = {
                "port":          pno,
                "tx_mbps":       round(tx_mbps, 3),
                "rx_mbps":       round(rx_mbps, 3),
                "tx_util_pct":   round(min(tx_mbps / LINK_CAPACITY_MBPS * 100, 100), 1),
                "rx_util_pct":   round(min(rx_mbps / LINK_CAPACITY_MBPS * 100, 100), 1),
                "tx_bytes":      tx_b,
                "rx_bytes":      rx_b,
                "tx_packets":    tx_pk,
                "rx_packets":    rx_pk,
                "tx_errors":     tx_err,
                "rx_errors":     rx_err,
                "timestamp":     round(now, 2),
            }

    # ── Helper methods ─────────────────────────────────────────────

    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Convenience wrapper to install a flow table entry."""
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        inst    = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod     = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        datapath.send_msg(mod)

    def _request_port_stats(self, datapath):
        """Send a port statistics request to one switch."""
        parser = datapath.ofproto_parser
        req    = parser.OFPPortStatsRequest(datapath, 0,
                                             datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def _monitor_loop(self):
        """Background thread: poll all connected switches every POLL_INTERVAL s."""
        while True:
            for dp in list(self.datapaths.values()):
                self._request_port_stats(dp)
            hub.sleep(self.POLL_INTERVAL)


# ── REST API handler ───────────────────────────────────────────────

class StatsController(ControllerBase):
    """
    Exposes collected port statistics as JSON over HTTP.
    
    Endpoints:
      GET /stats/all          → all switches and their port stats
      GET /stats/<dpid>       → stats for a specific switch (dpid as int)
    """

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.monitor_app = data[MONITOR_INSTANCE_NAME]

    @route("monitor", "/stats/all", methods=["GET"])
    def get_all_stats(self, req, **kwargs):
        body = {
            str(dpid): ports
            for dpid, ports in self.monitor_app.port_stats.items()
        }
        return Response(
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
            body=json.dumps(body).encode("utf-8"),
        )

    @route("monitor", REST_URL, methods=["GET"])
    def get_switch_stats(self, req, **kwargs):
        dpid  = int(kwargs["dpid"])
        ports = self.monitor_app.port_stats.get(dpid, {})
        return Response(
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
            body=json.dumps(ports).encode("utf-8"),
        )
