"""Exercise native stderr/exit-code handling in the Windows startup helper."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 native stream regression")
@pytest.mark.parametrize(
    "exit_code,allow_failure,expected", [(0, False, "ok"), (7, False, "rejected"), (7, True, "ok")]
)
def test_compose_helper_uses_exit_code_not_progress_stderr(
    tmp_path: Path, exit_code: int, allow_failure: bool, expected: str
) -> None:
    # Extract only the function AST: never execute the startup script itself.
    # Python is a real native process emitting stderr and an exit code; no
    # database, Docker daemon or LLM is replaced by this test.
    script = tmp_path / "native-stream-check.ps1"
    script.write_text(
        """$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:STARTUP_SCRIPT, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Startup script syntax error' }
$function = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Compose'
}, $true)
. ([scriptblock]::Create($function.Extent.Text))
Set-Alias docker $env:NATIVE_TEST_PYTHON
$ComposeArgs = @('-c', "import sys; sys.stderr.write('normal progress\\n'); sys.exit(int(sys.argv[1]))")
try {
    Invoke-Compose -Arguments @($env:NATIVE_TEST_EXIT) -Quiet -AllowFailure:($env:NATIVE_ALLOW_FAILURE -eq 'true')
    Write-Output 'ok'
} catch {
    Write-Output 'rejected'
}
""",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "STARTUP_SCRIPT": str(REPO_ROOT / "scripts/dev.ps1"),
        "NATIVE_TEST_PYTHON": sys.executable,
        "NATIVE_TEST_EXIT": str(exit_code),
        "NATIVE_ALLOW_FAILURE": str(allow_failure).lower(),
    }
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
