from datetime import datetime
from pathlib import Path
from data_load import extraer, cargar_bq, TABLAS

BASE = Path(__file__).parent
LOG = BASE / "etl_log.txt"

def log(linea):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{fecha} | {linea}\n")

def main():
    for sql_file, (table, incremental) in TABLAS.items():
        try:
            df = extraer(sql_file)
            cargar_bq(df, table, incremental)
            log(f"OK - {df.shape[0]} filas en {table}")
        except Exception as e:
            log(f"FALLO - {table} - {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()