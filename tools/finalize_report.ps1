# =====================================================================
# Cap nhat field/TOC va xuat PDF cho BaoCao.docx bang Word COM.
# Chay: powershell -ExecutionPolicy Bypass -File tools\finalize_report.ps1
# =====================================================================
param(
    [string]$DocxPath = "",
    [string]$PdfPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DocxPath)) {
    $DocxPath = Join-Path $root "reports\BaoCao.docx"
}
if ([string]::IsNullOrWhiteSpace($PdfPath)) {
    $PdfPath = Join-Path $root "reports\BaoCao.pdf"
}
$DocxPath = [System.IO.Path]::GetFullPath($DocxPath)
$PdfPath = [System.IO.Path]::GetFullPath($PdfPath)

if (-not (Test-Path -LiteralPath $DocxPath)) {
    throw "Khong tim thay DOCX: $DocxPath"
}
$pdfDir = Split-Path -Parent $PdfPath
if (-not (Test-Path -LiteralPath $pdfDir)) {
    New-Item -ItemType Directory -Path $pdfDir | Out-Null
}

Write-Host "Mo Word de cap nhat field..."
$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.ScreenUpdating = $false

    # ConfirmConversions=false, ReadOnly=false, AddToRecentFiles=false
    $doc = $word.Documents.Open($DocxPath, $false, $false, $false)

    function Update-AllFields {
        $current = $doc.StoryRanges.Item(1)
        while ($null -ne $current) {
            $current.Fields.Update() | Out-Null
            $current = $current.NextStoryRange
        }
    }

    function Update-TocFields {
        foreach ($field in $doc.Fields) {
            if ($field.Code.Text -match '^\s*TOC\b') {
                $field.Update() | Out-Null
            }
        }
    }

    # Cap nhat field o moi story: than van, header, footer, footnote, endnote.
    Update-AllFields
    Update-TocFields

    # Dinh dang cac style muc luc sau khi Word da tao chung. Cach nay tranh
    # viec Word dung style mac dinh qua lon (13 pt, gian dong 1,5).
    foreach ($styleName in @("toc 1", "toc 2", "toc 3", "Table of Figures")) {
        $style = $null
        try { $style = $doc.Styles.Item($styleName) } catch { }
        if ($null -eq $style) { continue }
        $style.Font.Name = "Times New Roman"
        $style.Font.Size = 11.5
        $style.ParagraphFormat.SpaceBefore = 0
        $style.ParagraphFormat.SpaceAfter = 0.5
        $style.ParagraphFormat.LineSpacingRule = 5   # wdLineSpaceMultiple
        $style.ParagraphFormat.LineSpacing = 11.8
    }

    # Cap nhat lai sau khi doi style vi so trang co the thay doi.
    Update-AllFields
    Update-TocFields
    $doc.Repaginate()
    $doc.Save()

    $tocFields = @()
    foreach ($field in $doc.Fields) {
        if ($field.Code.Text -match '^\s*TOC\b') {
            $tocFields += $field
        }
    }
    $pages = $doc.ComputeStatistics(2)  # wdStatisticPages
    Write-Host ("So trang sau khi cap nhat: {0}" -f $pages)
    Write-Host ("So field TOC: {0}" -f $tocFields.Count)
    for ($i = 0; $i -lt $tocFields.Count; $i++) {
        $text = $tocFields[$i].Result.Text
        $lines = ($text -split "`r" | Where-Object { $_.Trim().Length -gt 0 }).Count
        Write-Host ("  TOC {0}: {1} dong" -f ($i + 1), $lines)
    }

    Write-Host "Xuat PDF..."
    $doc.ExportAsFixedFormat(
        $PdfPath,
        17,      # wdExportFormatPDF
        $false,  # OpenAfterExport
        0,       # wdExportOptimizeForPrint
        0,       # wdExportAllDocument
        0,       # From
        0,       # To
        0,       # wdExportDocumentContent
        $true,   # IncludeDocProps
        $true,   # KeepIRM
        1,       # wdExportCreateHeadingBookmarks
        $true,   # DocStructureTags
        $true,   # BitmapMissingFonts
        $false   # UseISO19005_1
    )

    Write-Host ("Da luu: {0}" -f $DocxPath)
    Write-Host ("Da xuat: {0}" -f $PdfPath)
}
finally {
    if ($null -ne $doc) {
        $doc.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) | Out-Null
    }
    if ($null -ne $word) {
        $word.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
