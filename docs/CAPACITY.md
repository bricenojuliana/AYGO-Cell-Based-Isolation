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

Se usa **m = 50** (100 rps, unas 80 WCU/s solo del ruidoso). La demanda queda en 126 WCU/s frente a 100 en el pool y en 94 frente a 25 en su celda. Ese cálculo ignora la capacidad de ráfaga; la corrección está abajo.

### Corrección tras la corrida P-E1-r1: la capacidad de ráfaga

DynamoDB acumula la capacidad no usada de los últimos 300 s y la gasta en ráfagas. La reserva depende de la holgura de cada tabla:

| Tabla | Holgura en estado normal | Reserva máxima (300 s) | Exceso con m = 50 | Tiempo hasta agotarla |
|---|---|---|---|---|
| Celda (25 WCU) | unas 9 WCU/s | unas 2.700 | unas 69 WCU/s | unos 40 s |
| Pool (100 WCU) | unas 52 WCU/s | unas 15.600 | unas 26 WCU/s | unos 600 s, más que la falla |

Por eso, con m = 50, la celda del ruidoso se satura pero el pool no: en P-E1-r1 solo el 7 % de los vecinos salió afectado. No es un error del experimento; es el efecto de multiplexación del pool, que comparte una holgura más grande.

Para medir también el caso en que el pool se satura se agrega el escenario **E1S** (ruido severo, m = 200, 400 rps): el pool recibe unas 366 WCU/s frente a 100, un exceso de unas 270 WCU/s que agota la reserva en alrededor de un minuto. Así el paper compara ruido moderado (E1) contra severo (E1S).

## Costo de las tablas

Precios públicos de capacidad aprovisionada en us-east-1 (verificar en la página de precios de DynamoDB): unos USD 0,00065 por WCU-hora y USD 0,00013 por RCU-hora. Con 200 WCU y 200 RCU, unos **USD 0,16 por hora** aunque no haya tráfico. Lambda, API Gateway y CloudWatch cobran por uso.
