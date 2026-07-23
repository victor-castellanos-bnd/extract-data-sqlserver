from dotenv import load_dotenv
from pathlib import Path
from google.cloud import bigquery
from google.oauth2 import service_account
import os
import pyodbc
import pandas as pd

load_dotenv()
BASE = Path(__file__).parent.parent

PROJECT = os.getenv("GCP_PROJECT")
DATASET = os.getenv("GCP_DATASET")

creds = service_account.Credentials.from_service_account_file(BASE / "credentials.json")
client = bigquery.Client(credentials=creds, project=PROJECT)

TABLAS = {
    "polizas.sql":     ("compaq_journal_entries", True),
    "movimientos.sql": ("compaq_journal_entry_lines", True),
    "cuentas.sql":     ("compaq_accounts", False),
    "saldos.sql":      ("compaq_account_balances", False), 
}

def extraer(sql_file):
    conn_str = (
        f"DRIVER={{{os.getenv('SQL_DRIVER')}}};"
        f"SERVER={os.getenv('SQL_SERVER')};"
        f"DATABASE={os.getenv('SQL_DB')};"
        f"UID={os.getenv('SQL_USER')};"
        f"PWD={os.getenv('SQL_PWRD')};"
        f"TrustServerCertificate=yes;"
    )
    query = (BASE / "sql" / sql_file).read_text(encoding="utf-8")
    conn = pyodbc.connect(conn_str)
    df = pd.read_sql(query, conn)
    conn.close()
    return df


def cargar_bq(df, table, incremental=False):
    table_id = f"{PROJECT}.{DATASET}.{table}"

    # catalagos full load truncate
    if not incremental:
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
        job.result()
        print(f"OK - {client.get_table(table_id).num_rows} filas en {table} (full)")
        return 
    
    # transaccionales (polizas, movmientos)
    temp_id = f"{table_id}_temp"

    #1 subir a temp 
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    client.load_table_from_dataframe(df, temp_id, job_config=job_config).result()

    #2 borrar en la final el rango que trae la temp e insertar.
    merge_sql = f"""
     DELETE FROM `{table_id}`
    WHERE fecha >= (SELECT MIN(fecha) FROM `{temp_id}`);

    INSERT INTO `{table_id}`
    SELECT * FROM `{temp_id}`;
    """

    client.query(merge_sql).result()

    print(f"OK - {df.shape[0]} filas remplazadas en table {table} (incremental)")
    return