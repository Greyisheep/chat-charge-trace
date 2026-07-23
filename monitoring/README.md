# Oja Connect — Monitoring Stack

Agent traces for the "Chat, Charge, Trace" workshop.

The backend ships OpenTelemetry spans to the OTEL Collector, which forwards
them to Tempo. Grafana connects to Tempo and lets you explore individual traces.

## Architecture

```
Oja Connect backend
  spans: agent.turn, tools.*, checkout.*, delivery.*, monnify.*, orders.*
         │
         │  OTLP/HTTP  :4318
         ▼
   otel-collector
         │
         │  OTLP/gRPC  :4317  (internal)
         ▼
       tempo
         │
         │  Tempo datasource
         ▼
      grafana :3000
        (Explore → Tempo → TraceQL)
```

## Quick start

```bash
cd monitoring
docker compose up -d
```

Open http://localhost:3000 — no login needed.

Go to **Explore** (compass icon), select the **Tempo** datasource, and
switch to **Search** or **TraceQL** mode.

## Backend configuration

In the backend `.env`:

```env
OTEL_SERVICE_NAME=oja-connect-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # local dev
OTEL_TRACES_SAMPLER=always_on
```

When the backend runs inside Docker (i.e. `docker compose up` from the repo
root), use the collector's container name instead:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
```

That requires the backend container to be on the `oja-monitoring` network.
For the workshop the backend and monitoring stacks are kept separate; the
simplest path is to run the backend locally (`./run.sh`) and point it at
`http://localhost:4318`.

## Span hierarchy

Every trace is rooted in an agent turn or a live voice session:

```
agent.turn
├── tools.list_products
├── tools.get_product
├── tools.quote_delivery
│   └── delivery.geocode
└── tools.checkout
    ├── checkout.validate_product
    ├── checkout.geocode_destination
    │   └── delivery.geocode
    ├── checkout.flight_fare_lookup        (express path only)
    ├── checkout.compute_fee
    ├── checkout.create_order
    │   └── orders.create
    └── checkout.payment_event

agent.turn
└── tools.check_order_status
    └── orders.verify
        └── monnify.query_transaction

live.session                               (WebSocket voice path)
└── (same tool/child structure as above)
```

Monnify client spans (`monnify.authenticate`, `monnify.initialize_transaction`,
`monnify.query_transaction`) appear as children of the tool span that triggered
them.

## TraceQL queries to try in Grafana Explore

Paste these into the TraceQL box after selecting the Tempo datasource.

```
# All agent turns
{ name = "agent.turn" }

# All tool calls
{ name =~ "tools\\..*" }

# Full checkout pipeline (all nodes)
{ name =~ "checkout\\..*" }

# Express checkouts (flight fare lookup ran)
{ name = "checkout.flight_fare_lookup" }

# Turns that touched Monnify
{ name =~ "monnify\\..*" }

# Live voice sessions
{ name = "live.session" }

# Slow turns (adjust threshold as needed)
{ name = "agent.turn" } | duration > 3s

# Any span that errored
{ status = error }
```

Click a trace in the results to open the waterfall. Each row is one span;
the width is its duration relative to the root. Child spans nest under their
parents to show the call graph.

## Deploying to a remote VM

Rsync this folder to the VM (the app itself stays wherever it runs):

```bash
rsync -av monitoring/ user@vm-ip:/opt/oja-monitoring/
```

Start the stack on the VM:

```bash
ssh user@vm-ip
cd /opt/oja-monitoring
docker compose up -d
```

Open port **4318** (collector ingress) and **3000** (Grafana) in the VM's
firewall.

Update the backend `.env` to point the exporter at the VM:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://vm-ip:4318
```

Grafana is then at `http://vm-ip:3000`.

## Troubleshooting

**No traces appear in Grafana**

1. Check the monitoring stack is healthy:
   ```bash
   docker compose ps
   curl http://localhost:3200/ready   # should print "ready"
   ```

2. Check the backend is sending spans — look for OTEL-related log lines at
   startup. If `OTEL_EXPORTER_OTLP_ENDPOINT` is wrong the backend logs a
   warning but keeps running.

3. Confirm the time range in Grafana Explore covers when you sent the request.
   Tempo defaults to the last 1 hour; widen it if needed.

**Grafana shows no Tempo datasource**

The provisioning file is mounted at container start. If you added it after
Grafana was already running:

```bash
docker compose restart grafana
```

**Spans appear as unconnected roots instead of a tree**

This can happen for the checkout fan-out nodes (`express_base_quote` and
`flight_fare_lookup`) when ADK dispatches them as separate async tasks.
The spans are still there and timestamped correctly — you can follow the
story by reading them in order even without a parent link.
