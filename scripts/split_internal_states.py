"""
Migra los CSV de resultados al formato de archivos separados.

Antes: <nombre>_results.csv contenia time, vin, i(v1) y todos los estados
internos, lo que generaba archivos enormes solo para ver una curva IV.

Ahora: <nombre>_results.csv queda con time, vin, i(v1) (mas los comentarios
de tiempos de ejecucion al pie) y los estados internos se mueven a
<nombre>_states.csv con el tiempo como columna de referencia.

Uso:
    python scripts/split_internal_states.py [ruta_simulation_results]

Por defecto procesa memristorsimulation_app/simulation_results. Los archivos
que ya tienen 3 columnas o menos se dejan como estan. El archivo original se
reemplaza (no se conserva copia), escribiendo primero a archivos temporales
para no perder datos si el proceso se interrumpe.
"""

import os
import sys

DEFAULT_RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memristorsimulation_app",
    "simulation_results",
)
IV_COLUMN_COUNT = 3  # time, vin, i(v1)
# Buffer grande para leer/escribir en bloques: los CSV pesan cientos de MB y
# con el buffering por defecto la escritura linea a linea es muy lenta.
IO_BUFFER_SIZE = 16 * 1024 * 1024


def split_results_csv(results_path: str) -> str:
    """
    Divide un *_results.csv en IV + estados. Devuelve un string con el
    resultado ("split", "skipped_small", "skipped_empty" o "skipped_states_exists").
    """
    states_path = results_path[: -len("_results.csv")] + "_states.csv"
    if os.path.exists(states_path):
        return "skipped_states_exists"

    with open(results_path, errors="replace") as f:
        header = f.readline()
    header_fields = header.split()
    if not header_fields:
        return "skipped_empty"
    if len(header_fields) <= IV_COLUMN_COUNT:
        return "skipped_small"

    tmp_results_path = results_path + ".tmp"
    tmp_states_path = states_path + ".tmp"

    results_rows = states_rows = 0
    with open(
        results_path, errors="replace", buffering=IO_BUFFER_SIZE
    ) as source, open(
        tmp_results_path, "w", newline="\n", buffering=IO_BUFFER_SIZE
    ) as results_out, open(
        tmp_states_path, "w", newline="\n", buffering=IO_BUFFER_SIZE
    ) as states_out:
        for line in source:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                # Comentarios (tiempos de ejecucion) y lineas vacias quedan
                # en el archivo de resultados, como hasta ahora.
                results_out.write(line if line.endswith("\n") else line + "\n")
                continue

            fields = stripped.split()
            results_out.write(" ".join(fields[:IV_COLUMN_COUNT]) + "\n")
            states_out.write(" ".join([fields[0]] + fields[IV_COLUMN_COUNT:]) + "\n")
            results_rows += 1
            states_rows += 1

    if results_rows != states_rows or results_rows == 0:
        os.remove(tmp_results_path)
        os.remove(tmp_states_path)
        raise RuntimeError(
            f"Inconsistencia al dividir {results_path}: "
            f"{results_rows} filas IV vs {states_rows} filas de estados"
        )

    os.replace(tmp_states_path, states_path)
    os.replace(tmp_results_path, results_path)
    return "split"


def main() -> None:
    results_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RESULTS_DIR
    if not os.path.isdir(results_dir):
        raise SystemExit(f"No existe el directorio {results_dir}")

    counters = {}
    for root, _, files in os.walk(results_dir):
        for file_name in sorted(files):
            if not file_name.endswith("_results.csv"):
                continue
            results_path = os.path.join(root, file_name)
            try:
                outcome = split_results_csv(results_path)
            except Exception as error:
                outcome = "error"
                print(f"[ERROR] {results_path}: {error}", flush=True)
            counters[outcome] = counters.get(outcome, 0) + 1
            if outcome == "split":
                print(f"[OK] {results_path}", flush=True)

    print("\nResumen:")
    for outcome, count in sorted(counters.items()):
        print(f"  {outcome}: {count}")


if __name__ == "__main__":
    main()
