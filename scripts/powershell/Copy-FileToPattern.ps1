<#
.SYNOPSIS
Copies a file to multiple destinations matching a wildcard path pattern.

.DESCRIPTION
This script copies a specified source file to multiple target directories defined 
by a wildcard-based destination pattern. Use '*' in any folder segment to match 
any directory name. Existing files are not overwritten unless you use -Force.

https://gist.github.com/Kenya-West/b9bc55a9c792f9cd8680f727f9b24b4a

.PARAMETER SourcePath
Path (relative or absolute) to the source file.

.PARAMETER DestinationPattern
A path containing wildcards that specifies the target directories and file name,
e.g. .\*\analytics\file.yml

.PARAMETER Force
Switch parameter. If set, existing files will be overwritten.

.EXAMPLE
.\Copy-FileToPattern.ps1
#>

[CmdletBinding(SupportsShouldProcess=$true)]
Param(
    [Parameter(Position=0)]
    [string]$SourcePath,

    [Parameter(Position=1)]
    [string]$DestinationPattern,

    [switch]$Force
)

# Prompt if missing
if (-not $SourcePath) {
    $SourcePath = Read-Host 'Please enter file path (could be relative)'
}
if (-not (Test-Path -Path $SourcePath -PathType Leaf)) {
    Write-Error "Source file '$SourcePath' does not exist."
    exit 1
}

if (-not $DestinationPattern) {
    $DestinationPattern = Read-Host 'Please enter destination pattern (use * as wildcard for any directory name)'
}

# Split into directory-pattern and file name
$DirPattern = Split-Path -Path $DestinationPattern -Parent
$FileName   = Split-Path -Path $DestinationPattern -Leaf

# Find matching directories
$Dirs = Get-ChildItem -Path $DirPattern -Directory -ErrorAction SilentlyContinue
if (-not $Dirs) {
    Write-Warning "No directories match the pattern '$DirPattern'."
    exit 1
}

Write-Host "Here's a list of paths the file will be copied to:`n"
$Dirs | ForEach-Object { Write-Host (Join-Path $_.FullName $FileName) }
Write-Host ""

# Perform the copies
foreach ($Dir in $Dirs) {
    $Dest = Join-Path $Dir.FullName $FileName
    Write-Host -NoNewline "Copying the file to path $Dest ... "

    if (Test-Path -Path $Dest -PathType Leaf) {
        if ($Force) {
            try {
                if ($PSCmdlet.ShouldProcess($Dest, "Overwrite with $SourcePath")) {
                    Copy-Item -Path $SourcePath -Destination $Dest -Force -ErrorAction Stop
                    Write-Host "success"
                } else {
                    Write-Host "skipped"
                }
            } catch {
                Write-Host "failure: $($_.Exception.Message)"
            }
        } else {
            Write-Host "will not be copied because file already exists"
        }
    } else {
        try {
            if ($PSCmdlet.ShouldProcess($Dest, "Copy to")) {
                Copy-Item -Path $SourcePath -Destination $Dest -ErrorAction Stop
                Write-Host "success"
            } else {
                Write-Host "skipped"
            }
        } catch {
            Write-Host "failure: $($_.Exception.Message)"
        }
    }
}

Write-Host "`nScript finished."
