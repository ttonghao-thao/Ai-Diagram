/** 企业组网图模板（与 fixtures/templates/enterprise_network.graph.json 保持同步）。 */
export const SAMPLE_ENTERPRISE_NETWORK = {
  "schemaVersion": "1.0",
  "diagramId": "enterprise_network",
  "name": "企业组网图（模板）",
  "diagramType": "network_topology",
  "groups": [
    {
      "id": "dmz_zone",
      "label": "DMZ 区"
    },
    {
      "id": "server_zone",
      "label": "核心业务区"
    },
    {
      "id": "access_zone",
      "label": "接入区"
    }
  ],
  "nodes": [
    {
      "id": "internet",
      "label": "互联网",
      "kind": "cloud"
    },
    {
      "id": "edge_router",
      "label": "出口路由器",
      "kind": "router"
    },
    {
      "id": "fw",
      "label": "防火墙",
      "kind": "firewall"
    },
    {
      "id": "vpn",
      "label": "VPN 网关",
      "kind": "generic",
      "properties": {
        "deviceType": "vpn_gateway"
      }
    },
    {
      "id": "lb",
      "label": "负载均衡",
      "kind": "generic",
      "properties": {
        "deviceType": "load_balancer"
      },
      "groupId": "dmz_zone"
    },
    {
      "id": "web1",
      "label": "Web 服务器",
      "kind": "server",
      "groupId": "dmz_zone"
    },
    {
      "id": "core_sw",
      "label": "核心交换机",
      "kind": "switch"
    },
    {
      "id": "acc_sw1",
      "label": "接入交换机 A",
      "kind": "switch",
      "groupId": "access_zone"
    },
    {
      "id": "acc_sw2",
      "label": "接入交换机 B",
      "kind": "switch",
      "groupId": "access_zone"
    },
    {
      "id": "ap1",
      "label": "无线 AP（办公区）",
      "kind": "generic",
      "properties": {
        "deviceType": "access_point"
      },
      "groupId": "access_zone"
    },
    {
      "id": "ap2",
      "label": "无线 AP（会议室）",
      "kind": "generic",
      "properties": {
        "deviceType": "access_point"
      },
      "groupId": "access_zone"
    },
    {
      "id": "app1",
      "label": "应用服务器",
      "kind": "server",
      "groupId": "server_zone"
    },
    {
      "id": "db1",
      "label": "核心数据库",
      "kind": "database",
      "groupId": "server_zone"
    }
  ],
  "edges": [
    {
      "id": "l1",
      "source": "internet",
      "target": "edge_router",
      "kind": "physical",
      "direction": "undirected",
      "label": "出口链路"
    },
    {
      "id": "l2",
      "source": "edge_router",
      "target": "fw",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l3",
      "source": "fw",
      "target": "core_sw",
      "kind": "physical",
      "direction": "undirected",
      "label": "Trunk 上联"
    },
    {
      "id": "l4",
      "source": "fw",
      "target": "vpn",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l5",
      "source": "fw",
      "target": "lb",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l6",
      "source": "lb",
      "target": "web1",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l7",
      "source": "core_sw",
      "target": "acc_sw1",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l8",
      "source": "core_sw",
      "target": "acc_sw2",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l9",
      "source": "acc_sw1",
      "target": "ap1",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l10",
      "source": "acc_sw2",
      "target": "ap2",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l11",
      "source": "core_sw",
      "target": "app1",
      "kind": "physical",
      "direction": "undirected"
    },
    {
      "id": "l12",
      "source": "app1",
      "target": "db1",
      "kind": "dataflow",
      "direction": "bidirectional",
      "label": "读写"
    }
  ],
  "layout": {
    "algorithm": "layered",
    "direction": "DOWN",
    "preserveManualPositions": true
  },
  "metadata": {
    "source": "template",
    "note": "典型企业组网骨架：出口→防火墙→核心→接入/无线/服务器分区；VPN 与 DMZ 旁挂。可按需增删。"
  }
} as const;
