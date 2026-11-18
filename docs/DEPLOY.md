# Despliegue en AWS Academy Learner Lab (CloudShell)

Todo corre en **CloudShell**, que ya trae `aws`, `sam`, `git`, Python y `boto3`, y usa la sesión del lab. No se escriben credenciales en ningún archivo.

## 0. Una sola vez por cuenta

```bash
git clone https://github.com/bricenojuliana/AYGO-Cell-Based-Isolation.git ~/cellsaas && cd ~/cellsaas
# Rol único del lab (ADR-008) y secreto para el hash de las API keys. Se guardan en ~/.bashrc,
# que persiste entre sesiones de CloudShell en la misma región.
echo "export ROLE_ARN=$(aws iam get-role --role-name LabRole --query Role.Arn --output text)" >> ~/.bashrc
echo "export CELLSAAS_PEPPER=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> ~/.bashrc
source ~/.bashrc
```

## 1. Desplegar plataforma (router, API, tabla de ruteo) y celdas (c1, c2, c3, q, pool)

```bash
cd ~/cellsaas && ./scripts/deploy.sh all      # ≈ 10-12 min la primera vez
```

Capacidad por celda: `CELL_RCU`, `CELL_WCU` (10 por defecto) y `RESERVED` (concurrencia reservada, 0 = sin reserva). El pool recibe 4× esa capacidad. Ejemplo: `CELL_WCU=5 ./scripts/deploy.sh cells`.

## 1b. Desplegar el plano de control (detector)

```bash
./scripts/deploy.sh control
python3 scripts/control.py mode observe   # detecta y audita, no aísla (C); "act" para C+IA
```

## 2. Registrar 30 tenants y probar

```bash
python3 scripts/tenants.py create --count 30   # crea tenants.json con las API keys (no subir a git)
python3 scripts/tenants.py show
export API=$(aws cloudformation describe-stacks --stack-name cellsaas-platform \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
python3 scripts/smoke.py "$API"
```

Las 5 líneas deben salir `PASS`. Guarda la salida en `docs/evidence/`.

## 3. Cambiar de topología sin redesplegar

```bash
python3 scripts/tenants.py topology pool    # configuración P
python3 scripts/tenants.py topology cells   # configuraciones C y C+IA
```

## 4. Inyectar o quitar una falla

```bash
python3 scripts/fault.py c2 --error-rate 1.0
python3 scripts/fault.py c2 --off
```

## 5. Borrar todo al terminar

```bash
for s in cellsaas-control cellsaas-cell-c1 cellsaas-cell-c2 cellsaas-cell-c3 cellsaas-cell-q cellsaas-cell-pool cellsaas-platform; do
  sam delete --stack-name "$s" --no-prompts
done
```

## Costo aproximado

Las tablas aprovisionadas (4 celdas × 10 RCU/WCU + pool 40/40) cuestan del orden de USD 0,06 por hora aunque no haya tráfico; Lambda y API Gateway cobran por petición. Borra las pilas si no vas a usarlas en varios días.
