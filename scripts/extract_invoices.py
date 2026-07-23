"""
Lee los Excel mensuales de facturas emitidas desde una carpeta de Google Drive
(un archivo por mes: 2026-01.xlsx, 2026-02.xlsx...), los junta, se queda con las
columnas que sirven para reportes, y los sube a BigQuery como una sola tabla.

Estilo plano y autocontenido, mismo patron que data_load.py: todo en un archivo,
sin modulos compartidos, credenciales por .env + credentials.json.
"""

from dotenv import load_dotenv
from pathlib import Path
import io
import os
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()
BASE = Path(__file__).parent.parent

# --- BigQuery ---
PROJECT = os.getenv("GCP_PROJECT")
DATASET = os.getenv("GCP_DATASET")
TABLE = "xls_facturas_emitidas"

# --- Drive ---
DRIVE_FOLDER_ID = os.getenv("DRIVE_FACTURAS_FOLDER_ID")
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# credenciales: BQ usa las de siempre; Drive usa su propia service account
creds_bq = service_account.Credentials.from_service_account_file(BASE / "credentials.json")
creds_drive = service_account.Credentials.from_service_account_file(
    BASE / "credentials_drive.json", scopes=DRIVE_SCOPES
)

bq_client = bigquery.Client(credentials=creds_bq, project=PROJECT)
drive_service = build("drive", "v3", credentials=creds_drive)

# Las ~20 columnas que sirven. El Excel trae ~61 (desglose de IEPS,
# direcciones, residencia fiscal, etc.) que se descartan.
# Llave = nombre tal cual viene en el Excel. Valor = nombre final en BigQuery.
COLUMNAS = {
    "Estado SAT":         "estado_cfdi",
    "Tipo":               "tipo_comprobante",
    "Fecha Emision":      "fecha_emision",
    "Serie":              "serie",
    "Folio":              "folio",
    "UUID":               "uuid",
    "RFC Emisor":         "rfc_emisor",
    "Nombre Emisor":      "nombre_emisor",
    "RFC Receptor":       "rfc_receptor",
    "Nombre Receptor":    "nombre_receptor",
    "UsoCFDI":            "uso_cfdi",
    "SubTotal":           "subtotal",
    "Descuento":          "descuento",
    "IVA 16%":            "iva_16",
    "Total":              "total",
    "Moneda":             "moneda",
    "FormaDePago":        "forma_de_pago",
    "Metodo de Pago":     "metodo_de_pago",
    "Condicion de Pago":  "condicion_de_pago",
    "Conceptos":          "conceptos",
}


def listar_archivos():
    """Devuelve [{id, name}, ...] de los .xlsx en la carpeta de Drive."""
    query = f"'{DRIVE_FOLDER_ID}' in parents and name contains '.xlsx'"
    archivos = []
    page_token = None
    while True:
        resp = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
        ).execute()
        archivos.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return archivos


def descargar_archivo(file_id):
    """Baja un archivo de Drive a memoria (bytes)."""
    request = drive_service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def main():
    archivos = listar_archivos()
    if not archivos:
        print("No hay archivos .xlsx en la carpeta, nada que cargar")
        return

    frames = []
    for archivo in archivos:
        print(f"Leyendo {archivo['name']}")
        contenido = descargar_archivo(archivo["id"])
        df = pd.read_excel(io.BytesIO(contenido), sheet_name="XML")
        df["archivo_origen"] = archivo["name"]
        frames.append(df)

    # juntar todos los meses
    combinado = pd.concat(frames, ignore_index=True)

    # quedarse solo con las columnas relevantes + el origen, y renombrar
    presentes = {orig: dest for orig, dest in COLUMNAS.items() if orig in combinado.columns}
    faltantes = [c for c in COLUMNAS if c not in combinado.columns]
    if faltantes:
        print(f"Aviso: columnas esperadas que no venian en el Excel: {faltantes}")

    combinado = combinado[[*presentes.keys(), "archivo_origen"]].rename(columns=presentes)

    # normalizar la fecha (viene como texto DD/MM/YYYY)
    combinado["fecha_emision"] = pd.to_datetime(
        combinado["fecha_emision"], dayfirst=True, errors="coerce"
    ).dt.date

    # subir a BigQuery reemplazando la tabla completa
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True)
    job = bq_client.load_table_from_dataframe(combinado, table_id, job_config=job_config)
    job.result()
    print(f"OK - {bq_client.get_table(table_id).num_rows} filas en {TABLE}")


if __name__ == "__main__":
    main()