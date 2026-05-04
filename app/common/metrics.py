"""
Métriques Prometheus centralisées

Module partagé pour éviter la duplication des métriques entre features.
"""
from prometheus_client import Counter, Histogram

# Compteur de requêtes
REQUEST_COUNT = Counter(
    'myia_requests',
    'Total requests by endpoint, method and status',
    ['endpoint', 'method', 'status']
)

# Histogramme des latences
REQUEST_LATENCY = Histogram(
    'myia_request_latency_seconds',
    'Request latency by endpoint',
    ['endpoint'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)
