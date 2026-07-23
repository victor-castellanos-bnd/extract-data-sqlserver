SELECT
    Id,
    IdPoliza,
    IdCuenta,
    Ejercicio,
    Periodo,
    TipoPol,
    Folio,
    TipoMovto,
    Importe,
    Referencia,
    Concepto,
    Fecha
FROM dbo.MovimientosPoliza
WHERE Fecha >= DATEADD(MONTH, -2, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
