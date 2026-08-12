[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('search', 'get', 'new', 'add', 'update', 'reclassify', 'reindex', 'validate', 'stats')]
    [string]$Action = 'search',

    [string]$Query,
    [string]$Id,
    [string]$Title,
    [string]$Category,
    [string]$InputFile,
    [string]$Field,
    [string]$Value,
    [ValidateRange(1, 50)]
    [int]$Limit = 8
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptRoot
$ReferenceRoot = Join-Path $SkillRoot 'references'
$RecordRoot = Join-Path $ReferenceRoot 'records'
$IndexPath = Join-Path $ReferenceRoot 'index.tsv'
$TemplatePath = Join-Path $ReferenceRoot 'template.md'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$MutationMutexName = 'Local\CodexAgentErrorGuardMutation'

$RequiredFields = @(
    'Signature',
    'Date',
    'Repository and branch',
    'Related paths',
    'Trigger command or operation',
    'Increment task',
    'Confirmed cause or unknowns',
    'Ineffective actions',
    'Proven fix',
    'Allowed next actions',
    'Forbidden repeated actions',
    'Stop and ask the user when'
)

$Categories = @(
    'agent-tooling',
    'build-test',
    'database-migration',
    'dependency-network-provider',
    'filesystem-permission-lock',
    'process-port-runtime',
    'frontend-browser',
    'firmware-serial',
    'git-worktree',
    'service-integration',
    'other'
)

function Read-Utf8Text {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8Text {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporaryPath = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    $backupPath = $Path + '.' + [guid]::NewGuid().ToString('N') + '.bak'
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $Content, $Utf8NoBom)
        if (Test-Path -LiteralPath $Path) {
            [System.IO.File]::Replace($temporaryPath, $Path, $backupPath)
        } else {
            [System.IO.File]::Move($temporaryPath, $Path)
        }
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
        if (Test-Path -LiteralPath $backupPath) {
            Remove-Item -LiteralPath $backupPath -Force
        }
    }
}

function Write-Utf8NewText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $stream = New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        $bytes = $Utf8NoBom.GetBytes($Content)
        $stream.Write($bytes, 0, $bytes.Length)
    } finally {
        $stream.Dispose()
    }
}

function Invoke-WithMutationLock {
    param([Parameter(Mandatory = $true)][scriptblock]$Operation)
    $mutex = New-Object System.Threading.Mutex($false, $MutationMutexName)
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne(5000)
        if (-not $acquired) {
            throw 'Error Guard mutation lock timed out after 5 seconds.'
        }
        & $Operation
    } finally {
        if ($acquired) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

function Normalize-OneLine {
    param([AllowNull()][string]$Text)
    if ($null -eq $Text) {
        return ''
    }
    return (($Text -replace '[\r\n\t]+', ' ') -replace '\s{2,}', ' ').Trim()
}

function Parse-Record {
    param([Parameter(Mandatory = $true)][string]$Path)

    $text = Read-Utf8Text -Path $Path
    $heading = [regex]::Match(
        $text,
        '(?m)^###\s+(ERR-\d{8}-\d{3})\s+([a-z0-9][a-z0-9-]*)\s*$'
    )
    if (-not $heading.Success) {
        throw "Invalid record heading: $Path"
    }

    $values = [ordered]@{}
    foreach ($requiredField in $RequiredFields) {
        $pattern = '(?m)^-\s+' + [regex]::Escape($requiredField) + ':\s*(.*)$'
        $match = [regex]::Match($text, $pattern)
        if (-not $match.Success) {
            throw "Missing field '$requiredField': $Path"
        }
        $fieldValue = Normalize-OneLine -Text $match.Groups[1].Value
        if ([string]::IsNullOrWhiteSpace($fieldValue) -or $fieldValue -eq '<required>') {
            throw "Empty field '$requiredField': $Path"
        }
        $values[$requiredField] = $fieldValue
    }

    return [pscustomobject]@{
        Id = $heading.Groups[1].Value
        Title = $heading.Groups[2].Value
        Fields = $values
        Path = (Resolve-Path -LiteralPath $Path).Path
        Text = $text
    }
}

function Get-CategoryFromPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $parent = Split-Path -Parent $Path
    return Split-Path -Leaf $parent
}

function Resolve-Category {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [string]$RequestedCategory
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedCategory)) {
        if ($Categories -notcontains $RequestedCategory) {
            throw "Unknown category '$RequestedCategory'."
        }
        return $RequestedCategory
    }

    $titleText = $Record.Title.ToLowerInvariant()
    if ($titleText -match 'powershell|parser|tool-call|apply-patch|\brg-|regex|encoding|mojibake|context-(?:compression|exhaustion)|output-limit') {
        return 'agent-tooling'
    }

    $haystack = (
        $Record.Title + ' ' +
        $Record.Fields['Signature'] + ' ' +
        $Record.Fields['Repository and branch'] + ' ' +
        $Record.Fields['Related paths'] + ' ' +
        $Record.Fields['Trigger command or operation']
    ).ToLowerInvariant()

    $rules = [ordered]@{
        'firmware-serial' = 'esp32|platformio|firmware|partition|flash|upload|serial|com\d|idf'
        'frontend-browser' = 'playwright|chromium|browser|vite|frontend|node_modules|npm'
        'git-worktree' = '\bgit\b|worktree|staging|commit|repack|multi-pack|index.lock'
        'database-migration' = 'flyway|mysql|jdbc|schema|migration|database|\bsql\b'
        'filesystem-permission-lock' = 'access denied|permission|acl|cannot delete|remove-item|filesystem|file lock|directory not empty'
        'dependency-network-provider' = 'dns|network|registry|maven central|provider|nacos|mqtt|redis|connection refused|permission denied: connect'
        'process-port-runtime' = '\bprocess\b|\bport\b|address already in use|startup|shutdown|dev server|runtime lock'
        'service-integration' = 'spring|gateway|feign|auth session|tenant-service|user-service|device-service|monitor-service|ribbon|loadbalancer'
        'build-test' = 'maven|mvnw|compile|build|surefire|failsafe|junit|\btest\b|package|target/classes'
        'agent-tooling' = 'powershell|parser|unexpectedtoken|tool call|apply_patch|\brg\b|regex|encoding|mojibake|context compression|context exhaustion|output limit'
    }

    foreach ($entry in $rules.GetEnumerator()) {
        if ($haystack -match $entry.Value) {
            return $entry.Key
        }
    }
    return 'other'
}

function Get-Keywords {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$ResolvedCategory
    )

    $source = (
        $Record.Title + ' ' +
        $Record.Fields['Signature'] + ' ' +
        $Record.Fields['Trigger command or operation'] + ' ' +
        $Record.Fields['Related paths']
    ).ToLowerInvariant()
    $tokens = [regex]::Matches($source, '[a-z][a-z0-9_.:/-]{2,}') |
        ForEach-Object { $_.Value.Trim('`', '.', ',', ':', ';', '/', '\') } |
        Where-Object { $_.Length -ge 3 } |
        Sort-Object -Unique |
        Select-Object -First 24
    $keywordParts = @($ResolvedCategory) + @($tokens | ForEach-Object { [string]$_ })
    return Normalize-OneLine -Text ($keywordParts -join ' ')
}

function Get-RecordFiles {
    if (-not (Test-Path -LiteralPath $RecordRoot)) {
        return @()
    }
    return @(Get-ChildItem -LiteralPath $RecordRoot -Recurse -File -Filter 'ERR-*.md')
}

function Get-NextRecordId {
    $datePart = Get-Date -Format 'yyyyMMdd'
    $used = @(Get-RecordFiles | ForEach-Object {
        $match = [regex]::Match($_.BaseName, "^ERR-$datePart-(\d{3})$")
        if ($match.Success) {
            [int]$match.Groups[1].Value
        }
    })
    $next = if ($used.Count -eq 0) { 1 } else { ($used | Measure-Object -Maximum).Maximum + 1 }
    if ($next -gt 999) {
        throw "No free error ID remains for $datePart."
    }
    return 'ERR-{0}-{1:000}' -f $datePart, $next
}

function Build-IndexRows {
    $rows = @()
    foreach ($recordFile in Get-RecordFiles) {
        $record = Parse-Record -Path $recordFile.FullName
        $recordCategory = Get-CategoryFromPath -Path $recordFile.FullName
        if ($Categories -notcontains $recordCategory) {
            throw "Record has unknown category '$recordCategory': $($recordFile.FullName)"
        }
        $relativePath = $recordFile.FullName.Substring($SkillRoot.Length + 1) -replace '\\', '/'
        $rows += [pscustomobject][ordered]@{
            id = $record.Id
            category = $recordCategory
            date = $record.Fields['Date']
            title = $record.Title
            signature = $record.Fields['Signature']
            repository = $record.Fields['Repository and branch']
            record = $relativePath
            keywords = Get-Keywords -Record $record -ResolvedCategory $recordCategory
        }
    }

    $duplicateIds = @($rows | Group-Object id | Where-Object Count -gt 1)
    if ($duplicateIds.Count -gt 0) {
        throw "Duplicate record IDs: $($duplicateIds.Name -join ', ')"
    }

    return @($rows | Sort-Object @{ Expression = 'id'; Descending = $true })
}

function Write-Index {
    $rows = Build-IndexRows
    $csvLines = @($rows | ConvertTo-Csv -Delimiter "`t" -NoTypeInformation)
    Write-Utf8Text -Path $IndexPath -Content (($csvLines -join "`n") + "`n")
    Write-Output "Indexed $($rows.Count) records."
}

function Read-Index {
    if (-not (Test-Path -LiteralPath $IndexPath)) {
        throw "Index is missing. Run: error-guard.ps1 reindex"
    }
    return @(Import-Csv -LiteralPath $IndexPath -Delimiter "`t" -Encoding UTF8)
}

function Resolve-RecordPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $nativeRelative = $RelativePath -replace '/', [System.IO.Path]::DirectorySeparatorChar
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path $SkillRoot $nativeRelative))
    if (-not $fullPath.StartsWith($RecordRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Index record path escapes the record root: $RelativePath"
    }
    return $fullPath
}

function Invoke-Search {
    if ([string]::IsNullOrWhiteSpace($Query) -and [string]::IsNullOrWhiteSpace($Category)) {
        throw 'search requires -Query or -Category.'
    }
    if (-not [string]::IsNullOrWhiteSpace($Category) -and $Categories -notcontains $Category) {
        throw "Unknown category '$Category'."
    }

    $queryText = Normalize-OneLine -Text $Query
    $queryLower = $queryText.ToLowerInvariant()
    $queryTokens = @($queryLower -split '\s+' | Where-Object { $_ })
    $matches = @()

    foreach ($row in Read-Index) {
        if (-not [string]::IsNullOrWhiteSpace($Category) -and $row.category -ne $Category) {
            continue
        }
        $haystack = (
            $row.id + ' ' + $row.category + ' ' + $row.date + ' ' +
            $row.title + ' ' + $row.signature + ' ' +
            $row.repository + ' ' + $row.keywords
        ).ToLowerInvariant()
        $score = 0
        if ($queryLower -and $row.id.ToLowerInvariant() -eq $queryLower) {
            $score += 1000
        }
        if ($queryLower -and $row.signature.ToLowerInvariant().Contains($queryLower)) {
            $score += 200
        }
        foreach ($token in $queryTokens) {
            if ($haystack.Contains($token)) {
                $score += 10
            }
            if ($row.title.ToLowerInvariant().Contains($token)) {
                $score += 15
            }
        }
        if ($queryTokens.Count -eq 0 -or $score -gt 0) {
            $matches += [pscustomobject]@{
                Score = $score
                Row = $row
            }
        }
    }

    $selected = @($matches |
        Sort-Object @{ Expression = 'Score'; Descending = $true },
                    @{ Expression = { $_.Row.id }; Descending = $true } |
        Select-Object -First $Limit)

    if ($selected.Count -eq 0) {
        Write-Output 'No matching error record.'
        return
    }

    foreach ($match in $selected) {
        $row = $match.Row
        Write-Output "[$($row.id)] $($row.category) | $($row.date)"
        Write-Output "  $($row.signature)"
        Write-Output "  record: $($row.record)"
    }
}

function Invoke-Get {
    if ($Id -notmatch '^ERR-\d{8}-\d{3}$') {
        throw 'get requires -Id ERR-YYYYMMDD-NNN.'
    }
    $row = @(Read-Index | Where-Object id -eq $Id)
    if ($row.Count -eq 0) {
        throw "Unknown error ID: $Id"
    }
    if ($row.Count -gt 1) {
        throw "Duplicate index entries for: $Id"
    }
    $path = Resolve-RecordPath -RelativePath $row[0].record
    Write-Output (Read-Utf8Text -Path $path)
}

function Invoke-NewDraft {
    if ([string]::IsNullOrWhiteSpace($Id)) {
        $script:Id = Get-NextRecordId
    }
    if ($Id -notmatch '^ERR-\d{8}-\d{3}$') {
        throw 'new accepts an optional -Id ERR-YYYYMMDD-NNN.'
    }
    if ($Title -notmatch '^[a-z0-9][a-z0-9-]*$') {
        throw 'new requires a lowercase kebab-case -Title.'
    }
    if ($Categories -notcontains $Category) {
        throw 'new requires a valid -Category.'
    }
    if (@(Read-Index | Where-Object id -eq $Id).Count -gt 0) {
        throw "Error ID already exists: $Id"
    }

    $draftRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'agent-error-guard-drafts'
    $draftPath = Join-Path $draftRoot "$Id.md"
    $template = Read-Utf8Text -Path $TemplatePath
    $template = $template.Replace('ERR-YYYYMMDD-NNN', $Id).Replace(
        'short-kebab-title',
        $Title
    )
    $template = $template -replace '(?m)^-\s+([^:]+):\s*$', '- $1: <required>'
    Write-Utf8Text -Path $draftPath -Content $template
    Write-Output "Draft created: $draftPath"
    Write-Output "Category for add: $Category"
}

function Invoke-Add {
    if ([string]::IsNullOrWhiteSpace($InputFile)) {
        throw 'add requires -InputFile.'
    }
    $sourcePath = (Resolve-Path -LiteralPath $InputFile).Path
    $record = Parse-Record -Path $sourcePath
    $index = Read-Index
    $filesystemIds = @(Get-RecordFiles | ForEach-Object {
        ([regex]::Match($_.BaseName, '^ERR-\d{8}-\d{3}$')).Value
    })
    if (
        @($index | Where-Object id -eq $record.Id).Count -gt 0 -or
        $filesystemIds -contains $record.Id
    ) {
        throw "Error ID already exists: $($record.Id)"
    }
    $normalizedSignature = $record.Fields['Signature'].Trim().ToLowerInvariant()
    $sameSignature = @($index | Where-Object {
        $_.signature.Trim().ToLowerInvariant() -eq $normalizedSignature
    })
    if ($sameSignature.Count -gt 0) {
        throw "Signature already exists in $($sameSignature[0].id); update it instead."
    }

    $resolvedCategory = Resolve-Category -Record $record -RequestedCategory $Category
    $destination = Join-Path (Join-Path $RecordRoot $resolvedCategory) "$($record.Id).md"
    Write-Utf8NewText -Path $destination -Content ($record.Text.Trim() + "`n")
    Write-Index
    Write-Output "Added $($record.Id) to $resolvedCategory."
}

function Invoke-Update {
    if ($Id -notmatch '^ERR-\d{8}-\d{3}$') {
        throw 'update requires -Id ERR-YYYYMMDD-NNN.'
    }
    if ($RequiredFields -notcontains $Field) {
        throw "Unknown field '$Field'."
    }
    $cleanValue = Normalize-OneLine -Text $Value
    if ([string]::IsNullOrWhiteSpace($cleanValue)) {
        throw 'update requires a non-empty -Value.'
    }

    $row = @(Read-Index | Where-Object id -eq $Id)
    if ($row.Count -ne 1) {
        throw "Expected one index entry for $Id, found $($row.Count)."
    }
    $path = Resolve-RecordPath -RelativePath $row[0].record
    $record = Parse-Record -Path $path
    $pattern = '(?m)^-\s+' + [regex]::Escape($Field) + ':\s*.*$'
    $replacement = "- ${Field}: $cleanValue"
    $updated = [regex]::Replace($record.Text, $pattern, $replacement, 1)
    Write-Utf8Text -Path $path -Content ($updated.Trim() + "`n")
    Write-Index
    Write-Output "Updated $Id field '$Field'."
}

function Invoke-Reclassify {
    $moves = @()
    foreach ($recordFile in Get-RecordFiles) {
        $record = Parse-Record -Path $recordFile.FullName
        $currentCategory = Get-CategoryFromPath -Path $recordFile.FullName
        $resolvedCategory = Resolve-Category -Record $record -RequestedCategory $null
        if ($currentCategory -ne $resolvedCategory) {
            $destination = Join-Path (Join-Path $RecordRoot $resolvedCategory) "$($record.Id).md"
            $moves += [pscustomobject]@{
                Source = $recordFile.FullName
                Destination = $destination
                Id = $record.Id
                From = $currentCategory
                To = $resolvedCategory
            }
        }
    }

    foreach ($move in $moves) {
        $destinationParent = Split-Path -Parent $move.Destination
        if (-not (Test-Path -LiteralPath $destinationParent)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }
        if (Test-Path -LiteralPath $move.Destination) {
            throw "Cannot reclassify $($move.Id); destination already exists."
        }
        Move-Item -LiteralPath $move.Source -Destination $move.Destination
        Write-Output "$($move.Id): $($move.From) -> $($move.To)"
    }
    Write-Index
    Write-Output "Reclassified $($moves.Count) records."
}

function Invoke-Validate {
    $files = Get-RecordFiles
    $rows = Build-IndexRows
    $index = Read-Index

    if ($files.Count -ne $rows.Count) {
        throw "Record count mismatch: files=$($files.Count), rows=$($rows.Count)."
    }
    if ($index.Count -ne $rows.Count) {
        throw "Index count mismatch: index=$($index.Count), records=$($rows.Count)."
    }

    $expected = @($rows | ForEach-Object { $_.id + '|' + $_.record })
    $actual = @($index | ForEach-Object { $_.id + '|' + $_.record })
    $difference = @(Compare-Object $expected $actual)
    if ($difference.Count -gt 0) {
        throw 'Index content does not match record files. Run reindex.'
    }

    Write-Output "Validation passed: $($rows.Count) unique records, 12 required fields each."
}

function Invoke-Stats {
    $rows = Read-Index
    Write-Output "Total records: $($rows.Count)"
    $rows |
        Group-Object category |
        Sort-Object Name |
        ForEach-Object { Write-Output ("{0}: {1}" -f $_.Name, $_.Count) }
}

switch ($Action) {
    'search' { Invoke-Search }
    'get' { Invoke-Get }
    'new' { Invoke-WithMutationLock { Invoke-NewDraft } }
    'add' { Invoke-WithMutationLock { Invoke-Add } }
    'update' { Invoke-WithMutationLock { Invoke-Update } }
    'reclassify' { Invoke-WithMutationLock { Invoke-Reclassify } }
    'reindex' { Invoke-WithMutationLock { Write-Index } }
    'validate' { Invoke-Validate }
    'stats' { Invoke-Stats }
}
