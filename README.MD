# extract-data-sqlserver

ETL que extrae datos contables de **CONTPAQi** (SQL Server) y los carga en **Google BigQuery** para alimentar reportes de cierre mensual. Corre de forma desatendida mediante el Programador de tareas de Windows en el propio servidor.

---

## Índice

- [Arquitectura](#arquitectura)
- [Origen de datos](#origen-de-datos)
- [Estrategia de carga](#estrategia-de-carga)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Configuración (`.env`)](#configuración-env)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Uso](#uso)
- [Automatización (tarea programada)](#automatización-tarea-programada)
- [Logs](#logs)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Pendientes](#pendientes)

---

## Arquitectura

```
SQL Server (CONTPAQi, instancia local)
        │
        │  pyodbc + pandas   (scripts/data_load.py → extraer)
        ▼
   DataFrame en memoria
        │
        │  google-cloud-bigquery   (scripts/data_load.py → cargar_bq)
        ▼
   BigQuery  ── dataset sources ──┐
                                  ├─ compaq_journal_entries      (incremental)
                                  ├─ compaq_journal_entry_lines  (incremental)
                                  ├─ compaq_accounts             (full)
                                  └─ compaq_account_balances     (full)
```

Todo el proceso corre **dentro del servidor Windows** donde vive SQL Server. La base de datos nunca se expone a internet: el script se conecta a la instancia local y solo la salida hacia BigQuery sale por la red.

---

## Origen de datos

La fuente es una base de datos de CONTPAQi sobre SQL Server (instancia con nombre, puerto TCP dinámico). Se extraen cuatro tablas mediante consultas guardadas en `sql/`:

| Consulta (`sql/`)   | Tabla destino (BigQuery)        | Contenido                                   |
| ------------------- | ------------------------------- | ------------------------------------------- |
| `polizas.sql`       | `compaq_journal_entries`        | Encabezados de póliza (asientos contables)  |
| `movimientos.sql`   | `compaq_journal_entry_lines`    | Partidas / renglones de cada póliza         |
| `cuentas.sql`       | `compaq_accounts`               | Catálogo de cuentas                         |
| `saldos.sql`        | `compaq_account_balances`       | Saldos iniciales por cuenta y ejercicio     |

El acceso se realiza con un usuario dedicado de **solo lectura** (`db_datareader`), sin permisos de escritura sobre la base contable.

---

## Estrategia de carga

Cada tabla se carga según su naturaleza. El comportamiento se controla con un flag en el diccionario `TABLAS` de `scripts/data_load.py`:

**Tablas transaccionales** (`incremental=True`) — pólizas y movimientos:

- La consulta trae solo una **ventana de los últimos meses** (mes actual + anteriores), filtrando por la columna `fecha`.
- Los datos se suben a una tabla `_temp`, y luego se reemplaza en la tabla final únicamente el rango de fechas que trae la temp (`DELETE` por rango + `INSERT`).
- Así se **conserva el histórico** y solo se refresca la ventana reciente, capturando ajustes contables tardíos sin recargar toda la tabla.

**Tablas de catálogo** (`incremental=False`) — cuentas y saldos:

- Son pequeñas y no tienen dimensión temporal útil.
- Se recargan completas en cada corrida con `WRITE_TRUNCATE`.

> La primera vez se hace una **carga inicial** completa (histórico total, sin filtros) para poblar las tablas. A partir de ahí, las transaccionales operan en modo incremental.

---

## Requisitos

- Windows (servidor donde reside SQL Server)
- Python 3.11+ (probado en 3.14)
- **ODBC Driver 17 for SQL Server** instalado en Windows
- SQL Server en **modo de autenticación mixto** (para el usuario SQL de solo lectura)
- Una cuenta de servicio de Google Cloud con permisos sobre el dataset destino de BigQuery
- Salida a internet desde el servidor hacia Google Cloud

---

## Instalación

```powershell
# 1. Clonar el repo
git clone <url-del-repo>
cd extract-data-sqlserver

# 2. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

Colocar en la raíz del proyecto:

- `credentials.json` — la clave de la cuenta de servicio de Google Cloud
- `.env` — variables de conexión (ver abajo)

Ambos archivos están en `.gitignore` y **no se versionan**.

---

## Configuración (`.env`)

Crear un archivo `.env` en la raíz con estas variables (ver `.env.example`):

```dotenv
# --- SQL Server (origen) ---
SQL_DRIVER=ODBC Driver 17 for SQL Server
SQL_SERVER=localhost,<puerto>        # instancia local por puerto TCP
SQL_DB=<nombre_base_datos>
SQL_USER=<usuario_solo_lectura>
SQL_PWRD=<contraseña>

# --- BigQuery (destino) ---
GCP_PROJECT=<id_del_proyecto>
GCP_DATASET=sources                  # cambiar a un dataset sandbox para pruebas
```

> **Tip de pruebas:** apuntar `GCP_DATASET` a un dataset `sandbox` permite ensayar el pipeline (incluido el reemplazo incremental) sin tocar las tablas de producción.

---

## Estructura del proyecto

```
extract-data-sqlserver/
├── sql/
│   ├── polizas.sql
│   ├── movimientos.sql
│   ├── cuentas.sql
│   └── saldos.sql
├── scripts/
│   ├── data_load.py        # conexión, extracción y carga (extraer / cargar_bq / TABLAS)
│   └── main.py             # orquestador: recorre TABLAS, maneja errores y log
├── .venv/                  # (ignorado)
├── .env                    # (ignorado)
├── credentials.json        # (ignorado)
├── etl_log.txt             # (ignorado) log de corridas
├── requirements.txt
├── run_etl.bat             # lanzador para la tarea programada
└── README.md
```

---

## Uso

Ejecución manual del pipeline completo:

```powershell
.venv\Scripts\python.exe scripts\main.py
```

O mediante el lanzador (activa el intérprete correcto):

```powershell
.\run_etl.bat
```

`main.py` recorre las cuatro tablas. Si una falla, las demás continúan y el error queda registrado en el log por tabla.

---

## Automatización (tarea programada)

El pipeline se ejecuta solo mediante el **Programador de tareas de Windows**, apuntando a `run_etl.bat`.

Registro de la tarea (PowerShell **como Administrador**):

```powershell
$accion = New-ScheduledTaskAction -Execute "C:\ruta\al\proyecto\run_etl.bat"
$disparador = New-ScheduledTaskTrigger -Daily -At 7:00am
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask -TaskName "ETL_Polizas_COMPAC" -Action $accion -Trigger $disparador -Settings $config -Description "Extrae de SQL Server y carga a BigQuery" -User "<servidor>\<usuario>" -Password (Read-Host -AsSecureString "Contraseña") -RunLevel Highest
```

Notas:

- `-StartWhenAvailable` recupera la corrida si el equipo estaba apagado/suspendido a la hora programada.
- La tarea corre **aunque no haya sesión iniciada** (guarda la credencial del usuario). Si se cambia la contraseña de Windows, hay que re-registrar la tarea.
- El `run_etl.bat` invoca el intérprete del venv por ruta absoluta (`.venv\Scripts\python.exe`), no depende de `activate`, para que sea confiable en modo desatendido.

Ejecución manual desde el Programador: clic derecho en la tarea → **Ejecutar**.

Contenido de `run_etl.bat`:

```bat
@echo off
cd /d C:\ruta\al\proyecto
.venv\Scripts\python.exe scripts\main.py
```

---

## Logs

Cada corrida agrega una línea por tabla a `etl_log.txt`, con formato tipo CI:

```
2026-07-22 07:00 | OK - 39893 filas en compaq_journal_entry_lines
2026-07-22 07:00 | OK - 2221 filas en compaq_journal_entries
2026-07-22 07:00 | FALLO - compaq_accounts - BadRequest: <detalle>
```

En caso de fallo se registra el tipo de excepción y el mensaje, sin detener las demás tablas. El historial de la propia tarea (si corrió, a qué hora, con qué resultado) puede verse además en la pestaña **Historial** del Programador de tareas.

---

## Decisiones de diseño

- **No se expone SQL Server a internet.** El ETL corre dentro del servidor y se conecta a la instancia local; solo el tráfico hacia BigQuery sale por la red. Para una base contable, exponer el puerto a internet era un riesgo innecesario.
- **Se descartó GitHub Actions.** Un runner en la nube no puede alcanzar una base local sin exponerla o montar un self-hosted runner. Dado que el proceso es de baja frecuencia (cierres mensuales), el Programador de tareas de Windows es más simple y seguro.
- **Ventana incremental con reemplazo por rango.** En contabilidad es común capturar movimientos con fecha atrasada; una ventana de varios meses refrescada a diario captura esos ajustes sin recargar el histórico completo.
- **Consultas SQL externas.** Cada tabla tiene su `.sql` en `sql/`, separado del código, para poder ajustar filtros o agregar tablas sin tocar Python.
- **Usuario de solo lectura.** El acceso a la base contable es `db_datareader`; el ETL no puede escribir en el origen.

> Nota histórica: el proyecto arrancó asumiendo que la fuente era MySQL. Al inspeccionar el servidor resultó ser SQL Server (instancia CONTPAQi), lo que cambió el driver (`pyodbc`), la cadena de conexión (instancia por puerto TCP dinámico) y el dialecto SQL (`TOP` en vez de `LIMIT`).

---

## Pendientes

- **Energía del servidor:** si el equipo se suspende, la corrida de las 7am se pospone hasta que despierte. Conviene configurar que no se suspenda.
- **Reintentos automáticos:** actualmente, si el script falla a media corrida, el siguiente intento es hasta el día siguiente. Se puede añadir reintento automático (cada N minutos, M veces) a la configuración de la tarea.
- **Mapeo de `Ejercicio` → año:** la tabla de saldos identifica el año por un código interno de CONTPAQi, no por el año literal. El mapeo a año real se resolverá en la capa de analytics.
- **Limpieza de tablas `_temp`:** las temporales quedan en el dataset tras cada corrida. No estorban (se sobreescriben), pero podrían eliminarse al final del proceso.