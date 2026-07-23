SELECT
    Id,
    Fecha,
    Folio,
    Concepto
FROM dbo.Polizas
WHERE Fecha >= DATEADD(MONTH, -2, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))