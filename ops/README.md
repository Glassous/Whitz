# Ops

可观测性配置。

- `prometheus/prometheus.yml`：抓取 `server` 与 `agent-api` 的 `/metrics`
- `grafana/provisioning/datasources/prometheus.yml`：Grafana Prometheus 数据源自动配置

详见 [docs/deployment.md](../docs/deployment.md)。
