[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$JarPath,

    [ValidateSet("svg", "png")]
    [string]$Format = "svg"
)

$inputFile = (Resolve-Path -LiteralPath $InputPath -ErrorAction Stop).Path
$jarFile = (Resolve-Path -LiteralPath $JarPath -ErrorAction Stop).Path
$java = Get-Command java -ErrorAction Stop

& $java.Source -jar $jarFile "-t$Format" $inputFile
if ($LASTEXITCODE -ne 0) {
    throw "PlantUML rendering failed with exit code $LASTEXITCODE"
}

$output = [System.IO.Path]::ChangeExtension($inputFile, $Format)
if (-not (Test-Path -LiteralPath $output)) {
    throw "PlantUML did not create expected output: $output"
}

Get-Item -LiteralPath $output
