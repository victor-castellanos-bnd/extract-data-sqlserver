# Registra la tarea programada que corre el ETL de SQL Server a las 7am diario.
# Ejecutar en PowerShell COMO ADMINISTRADOR:
#     .\registrar_tarea.ps1
#
# Pide la contrasena del usuario en una ventana grafica (evita el problema
# de teclearla a ciegas con teclado Mac/Windows).

$rutaBat = "C:\Users\Admin_apps\extract-data-sqlserver\run_etl.bat"
$usuario = "server\admin_apps"    # ajustar si el nombre de usuario cambia (ver con: whoami)

$accion     = New-ScheduledTaskAction -Execute $rutaBat
$disparador = New-ScheduledTaskTrigger -Daily -At 7:00am
$config     = New-ScheduledTaskSettingsSet -StartWhenAvailable

# ventana grafica para la contrasena, en vez de teclearla a ciegas
$cred = Get-Credential $usuario

Register-ScheduledTask `
    -TaskName "ETL_Polizas_COMPAC" `
    -Action $accion `
    -Trigger $disparador `
    -Settings $config `
    -Description "Extrae de SQL Server (COMPAC22) y carga a BigQuery" `
    -User $cred.UserName `
    -Password $cred.GetNetworkCredential().Password `
    -RunLevel Highest

Write-Host "Tarea registrada. Verifica en el Programador de tareas o corre:"
Write-Host "  Get-ScheduledTask -TaskName 'ETL_Polizas_COMPAC'"