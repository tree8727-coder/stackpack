<#
  stackpack 설치 — 처음 쓰는 분용.

  이 스크립트가 하는 일은 셋뿐입니다.
    1. uv (파이썬 실행기)가 없으면 깝니다.
    2. 스택팩이 돌아가는지 확인합니다.
    3. 지금 PC에 무엇이 이미 깔려 있는지 보여줍니다.

  도구를 마음대로 깔지 않습니다. 그건 확인하고 나서 직접 고르는 겁니다.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

function Say($text)  { Write-Host $text }
function Step($n, $text) { Write-Host "" ; Write-Host "[$n/3] $text" -ForegroundColor Cyan }
function Good($text) { Write-Host "  OK   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  !    $text" -ForegroundColor Yellow }
function Die($text, $how) {
    Write-Host ""
    Write-Host "  멈췄습니다: $text" -ForegroundColor Red
    if ($how) { Write-Host "  이렇게 하세요: $how" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "  그래도 안 되면 이 창을 통째로 캡처해서 카톡으로 보내주세요." -ForegroundColor Yellow
    Write-Host "  구매하신 분은 답변해 드립니다." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  엔터를 누르면 창이 닫힙니다"
    exit 1
}

function Refresh-Path {
    # winget으로 깐 프로그램은 지금 열려 있는 창의 PATH에 아직 없습니다. 다시 읽어옵니다.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $extra   = if ($env:USERPROFILE) { Join-Path $env:USERPROFILE '.local\bin' } else { $null }
    $env:Path = (@($machine, $user, $extra) | Where-Object { $_ }) -join ';'
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # 환경변수가 비어 있을 수 있습니다. 비면 그 후보만 건너뜁니다 —
    # 여기서 터지면 아래 winget 안내문이 나올 기회를 잃습니다.
    $candidates = @(
        @{ root = $env:USERPROFILE;  leaf = '.local\bin\uv.exe' },
        @{ root = $env:LOCALAPPDATA; leaf = 'Microsoft\WinGet\Links\uv.exe' }
    )
    foreach ($c in $candidates) {
        if (-not $c.root) { continue }
        $p = Join-Path $c.root $c.leaf
        if (Test-Path $p) { return $p }
    }
    return $null
}

Say ""
Say "  stackpack 설치를 시작합니다."
Say "  폴더: $here"

# --- 1. 준비물 확인 -----------------------------------------------------------
Step 1 "준비물 확인"

if (-not (Test-Path (Join-Path $here 'build.py'))) {
    Die "이 폴더에 build.py가 없습니다." "받으신 zip 파일의 압축을 풀고, 그 안에 있는 시작하기 파일을 실행해 주세요."
}
if (-not (Test-Path (Join-Path $here 'stack.yaml'))) {
    Die "이 폴더에 stack.yaml이 없습니다." "압축이 덜 풀렸을 수 있습니다. zip을 다시 풀어 주세요."
}
Good "스택팩 파일 확인"

$uv = Find-Uv
if ($uv) {
    Good "uv 이미 있음 ($uv)"
} else {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Die "winget이 없습니다." "Microsoft Store에서 '앱 설치 관리자'(App Installer)를 설치한 뒤 다시 실행해 주세요."
    }
    Warn "uv가 없어서 지금 깝니다. 1~2분 걸립니다."
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $uv = Find-Uv
    if (-not $uv) {
        Die "uv를 깔았는데 찾지 못했습니다." "이 창을 닫고 새 창에서 다시 실행해 주세요. 그러면 대부분 해결됩니다."
    }
    Good "uv 설치 완료 ($uv)"
}

# --- 2. 스택팩이 도는지 확인 ---------------------------------------------------
Step 2 "스택팩이 도는지 확인"

Push-Location $here
try {
    & $uv run build.py selftest
    if ($LASTEXITCODE -ne 0) {
        Die "자체 검사가 실패했습니다." "받으신 파일이 손상됐을 수 있습니다. 카톡으로 알려주시면 다시 보내드립니다."
    }
    Good "자체 검사 통과"

    # --- 3. 내 PC 상태 ---------------------------------------------------------
    Step 3 "지금 이 PC에 무엇이 깔려 있나"
    & $uv run build.py status
} finally {
    Pop-Location
}

Say ""
Write-Host "  준비 끝났습니다." -ForegroundColor Green
Say ""
Say "  이제부터는 이 폴더에서 아래를 씁니다. 복사해서 붙여넣으세요."
Say ""
Say "    uv run build.py status content-factory" -ForegroundColor Cyan
Say "      → 콘텐츠 공장 콤보에 뭐가 필요한지만 봅니다."
Say ""
Say "    uv run build.py install content-factory --skip-installed" -ForegroundColor Cyan
Say "      → 없는 것만 '미리보기'. 아무것도 깔지 않습니다."
Say ""
Say "    uv run build.py install content-factory --skip-installed --yes" -ForegroundColor Cyan
Say "      → 여기서 실제로 깔립니다. --yes 를 붙였을 때만 실행됩니다."
Say ""
Say "  막히면 창을 통째로 캡처해서 카톡으로 보내주세요."
Say ""
Read-Host "  엔터를 누르면 창이 닫힙니다"
