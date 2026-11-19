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
