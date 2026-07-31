# Packet 07 browser metrics

Overall: **PASS**

- HTML build: 116.3 ms (3.86 MB)
- Exact-scale: 56862 v / 113720 f
- Best plot_ms: 1173 (wall 3171)
- Status: ready · 1173 ms
- CDN refs: 0

- PASS `exact_scale_paints_lt_2s`: {"pass":true,"best_plot_ms":1173,"best_wall_ms":3171,"runs":[{"plot_ms":2003,"wall_ms":3964},{"plot_ms":1173,"wall_ms":3171}]}
- PASS `no_cdn`: {"pass":true,"network":[{"url":"http://127.0.0.1:8787/exact_scale_local_plotly.html","method":"GET"},{"url":"http://127.0.0.1:8787/vendor/plotly-2.35.2.min.js","method":"GET"}]}
- PASS `aspectmode_data`: {"pass":true}
- PASS `failure_visible`: {"pass":true,"status":"error"}
