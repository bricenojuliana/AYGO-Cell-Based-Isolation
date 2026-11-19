# Corridas del experimento (desde el portátil)

La carga se genera desde el portátil y no desde CloudShell, porque CloudShell cierra la sesión por inactividad y una matriz completa dura horas. El portátil usa las credenciales temporales del Learner Lab; no se guardan en el repo.

## 1. Preparar el portátil (una vez)

```bash
git clone https://github.com/bricenojuliana/AYGO-Cell-Based-Isolation.git && cd AYGO-Cell-Based-Isolation
python3 -m venv .venv && . .venv/bin/activate
pip install -r experiments/requirements.txt
```

Descarga `tenants.json` desde CloudShell (Actions → Download file → `/home/cloudshell-user/cellsaas/tenants.json`) y cópialo a la raíz del repo. Está en `.gitignore`.

## 2. Credenciales del lab (cada vez que inicias el lab)

En el Learner Lab: **AWS Details → AWS CLI → Show**. Copia el bloque en `~/.aws/credentials` (perfil `[default]`). Luego:

```bash
export AWS_DEFAULT_REGION=us-east-1
aws sts get-caller-identity            # debe responder sin error
export API=$(aws cloudformation describe-stacks --stack-name cellsaas-platform \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
```

Las credenciales vencen cuando termina la sesión del lab (unas 4 horas). Si vencen a mitad de la matriz, renueva la sesión, vuelve a copiar el bloque y relanza el mismo comando: el runner salta las corridas que ya terminaron.

## 3. Corrida de prueba (unos 10 minutos)

```bash
python3 experiments/run.py --api "$API" --only C-E1 --reps 1
python3 experiments/analyze.py
```

Revisa en `results/runs.csv` que `affected_peak_pct` sea mayor que 0 y que en `results/timeline_E1.png` la curva suba durante la falla. Si la curva no sube, el ruido no alcanzó a saturar la celda (ver [CAPACITY.md](CAPACITY.md)) y se sube `--multiplier`.

## 4. Matriz completa

7 configuraciones × 3 repeticiones × unos 10 minutos ≈ 3,5 horas. Deja el portátil conectado y sin suspender.

```bash
python3 experiments/run.py --api "$API" --reps 3
python3 experiments/analyze.py
```

Salidas en `results/`: `runs.csv` (una fila por corrida), `summary.csv` (medianas), `tests.csv` (Mann-Whitney y delta de Cliff) y las figuras `timeline_*.png` y `box_*.png`. Los CSV crudos de `results/raw/` no se suben (pesan y no aportan); las tablas y figuras sí.

## 5. Al terminar

Borra las pilas (paso 5 de [DEPLOY.md](DEPLOY.md)) para no gastar presupuesto del lab.

## 6. Corridas ejecutadas

La cuenta del Learner Lab se desactivó el 2026-11-19 a mitad de la matriz, por el volumen de invocaciones Lambda de la prueba de carga (cada petición invoca al router y a una celda, unas 320 invocaciones por segundo durante dos horas). Se alcanzaron 8 corridas, una por condición salvo P-E4 (dos):

| Configuración | E0 | E1 | E4 |
|---|---|---|---|
| Pool (P) | r1 | r1 | r1, r3 |
| Celdas (C) | r1, r3 | r3 | — |
| Celdas + IA (CIA) | — | r1 | — |

Con una corrida por condición los resultados son descriptivos: no se reportan pruebas de Mann-Whitney ni delta de Cliff. E1S y C-E4 no se ejecutaron. La exportación del plano de control se perdió con la cuenta, así que la comparación z-score vs Isolation Forest usa las peticiones por tenant y minuto que registró el generador de carga (`results/tenant_minutes.csv`, `experiments/compare_detectors.py --client`).

Si se repite el experimento en otra cuenta, conviene una tasa base más baja (`--rate 0.5`) y coordinar la prueba de carga con el administrador de la cuenta.
