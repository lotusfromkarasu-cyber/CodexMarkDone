$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path $PSScriptRoot
$buildRoot = Join-Path $env:LOCALAPPDATA 'CodexMarkDone-build'
$pythonExe = Join-Path $buildRoot 'venv/Scripts/python.exe'
if (!(Test-Path $pythonExe)) {
    python -m venv "$buildRoot/venv"
}
& $pythonExe -m pip install pyinstaller==6.22.2 pystray==0.19.5 Pillow==12.3.0 python-docx==1.2.0 lxml==6.1.3 mathml2omml==0.0.2 pywin32==312
if ($LASTEXITCODE) { throw 'Dependencies failed' }
$iconSource = Join-Path $sourceRoot 'assets/CodexMarkDone.ico'
& $pythonExe (Join-Path $sourceRoot 'assets/generate_icon.py')
if ($LASTEXITCODE) { throw 'Icon generation failed' }
$destination = Join-Path $env:LOCALAPPDATA 'Programs'
& $pythonExe -m PyInstaller --noconfirm --windowed --onedir --name CodexMarkDone --icon "$iconSource" --add-data "$sourceRoot/web;web" --distpath $destination --workpath "$buildRoot/work" --specpath $buildRoot "$PSScriptRoot/reader_service.py"
if ($LASTEXITCODE) { throw 'Build failed' }
$exe = Join-Path $destination 'CodexMarkDone/CodexMarkDone.exe'
$shortcutShell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $shortcut = $shortcutShell.CreateShortcut((Join-Path $folder 'Codex MarkDone.lnk'))
    $shortcut.TargetPath = $exe
    $shortcut.WorkingDirectory = Split-Path $exe
    $shortcut.Description = 'Codex 本地阅读器与公式复制'
    $shortcut.IconLocation = "$exe,0"
    $shortcut.Save()
}
Write-Output "Installed: $exe"
