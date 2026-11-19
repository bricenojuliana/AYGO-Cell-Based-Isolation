# Dimensionamiento de capacidad

Datos de la fase 0 (Learner Lab, us-east-1): 1000 ejecuciones concurrentes de Lambda en la cuenta, sin restricciones para reservar por función; DynamoDB, SSM, EventBridge y CloudWatch disponibles con `LabRole`.

## Carga base

| Parámetro | Valor |
|---|---|
| Tenants | 30 (10 por celda en C y C+IA) |
| Tasa por tenant | 2 rps, Poisson, lazo abierto |
| Mezcla | 80 % crear pedido, 20 % leer pedido |
| Costo de crear | 1 WCU (ítem < 1 KB) |
| Costo de leer | 0,5 RCU (GetItem, lectura eventual) |

Por tenant en estado normal: 1,6 WCU/s. Una celda de 10 tenants usa unas 16 WCU/s; el pool con 30 tenants, unas 48 WCU/s.

El reporte diario se dejó fuera de la mezcla. Lee toda la partición del tenant, así que su costo crece con cada corrida; en la corrida de prueba (C-E1, 2026-11-19) saturó por sí solo la lectura de las celdas sanas y subió su p99 de 230 a 680 ms sin relación con el tenant ruidoso.

## Capacidad elegida

| Recurso | Celda (c1, c2, c3, q) | Pool |
|---|---|---|
| WCU / RCU aprovisionadas | 25 / 25 | 100 / 100 |
| Concurrencia reservada de la función | 20 | 80 |

La capacidad total es la misma en C y en P (4 × 25 = 100), así que la comparación no favorece a ninguna de las dos (SPEC §5). Ambas trabajan al 50-65 % de uso en estado normal. La concurrencia reservada suma 160 de 1000; las 840 restantes quedan para el router y el detector.

## Multiplicador del tenant ruidoso (E1)

El tenant ruidoso pasa a 2 × m rps, es decir 1,6 m WCU/s. Para que el experimento sea justo, el ruido debe saturar **las dos** topologías. Si solo saturara la celda pequeña, el resultado mediría tamaño y no aislamiento:

- Celda: 14,4 + 1,6 m > 25 → m > 6,6
- Pool: 46,4 + 1,6 m > 100 → m > 33,5

Se usa **m = 50** (100 rps, unas 80 WCU/s solo del ruidoso). La demanda queda en 126 WCU/s frente a 100 en el pool y en 94 frente a 25 en su celda.

DynamoDB guarda hasta 300 s de capacidad no usada como ráfaga. Con m = 50 el exceso (26 WCU/s en el pool) agota esa ráfaga en menos de dos minutos, dentro de la ventana de falla de 300 s. La corrida de prueba del jueves confirma que la saturación aparece. Si no aparece, se sube m sin cambiar la capacidad.

## Costo de las tablas

Precios públicos de capacidad aprovisionada en us-east-1 (verificar en la página de precios de DynamoDB): unos USD 0,00065 por WCU-hora y USD 0,00013 por RCU-hora. Con 200 WCU y 200 RCU, unos **USD 0,16 por hora** aunque no haya tráfico. Lambda, API Gateway y CloudWatch cobran por uso.
