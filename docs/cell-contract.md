# Contrato interno router → celda

La celda solo se invoca con `lambda:Invoke` desde el router. No tiene endpoint público.

Petición:

```json
{"op": "CreateOrder" | "GetOrder" | "DailyReport", "tenantId": "cafe-07", "requestId": "...",
 "body": {"items": [...]}, "orderId": "CC-7K3Q-9XMD", "day": "2026-11-19"}
```

Respuesta:

```json
{"status": 201, "body": {...}}
```

Errores de la celda: `400 INVALID_REQUEST`, `404 ORDER_NOT_FOUND`, `500 INJECTED_FAULT`, `503 CELL_SATURATED`.
Errores del router: `401 UNAUTHORIZED`, `403 TENANT_NOT_PLACED`, `429 CELL_THROTTLED`, `502 CELL_FAILED`, `503 CELL_UNAVAILABLE`.
