# scan-dpapi.ps1 - recover AES keys hidden in DPAPI-protected files
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scan-dpapi.ps1
#       -> scans %LOCALAPPDATA%\* recursively for small .bin/.dat/.key blobs
#
#   ... -Root "C:\Users\X\AppData\Local\SomeGame" -Entropy "SomeGame key v1"
#       -> explicit root + explicit DPAPI entropy string
#
#   ... -Out "D:\cands.txt" -MaxSize 2MB
#
# Output: one candidate per line (32 bytes = 64 hex chars, or longer windows).
# Verify them with:  node verify-cands.js --pak="<pak>" cands.txt
#
# Why this works: many re-host / crack bundles fetch the pak key from their own
# HTTP server, then cache it with CryptProtectData (DPAPI). The blob on disk is
# not the key, so byte scanning can never find it -- but the blob is decryptable
# by the same Windows user that played the game.

param(
  [string[]]$Root,
  [string]$Entropy = "",
  [string]$Out = "",
  [int]$MaxSize = 2097152,
  [switch]$AllWindows
)

$ErrorActionPreference = 'Continue'

if (-not $Out) { $Out = Join-Path $PSScriptRoot 'dpapi_cands.txt' }
if (-not $Root -or $Root.Count -eq 0) {
  $Root = @(Get-ChildItem $env:LOCALAPPDATA -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
}

$code = @'
using System;
using System.Runtime.InteropServices;

public static class Dp {
  [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern bool CryptUnprotectData(ref DATA_BLOB pDataIn, IntPtr ppszDataDescr,
    ref DATA_BLOB pOptionalEntropy, IntPtr pvReserved, IntPtr pPromptStruct, int dwFlags, ref DATA_BLOB pDataOut);

  [DllImport("kernel32.dll")]
  public static extern IntPtr LocalFree(IntPtr hMem);

  [StructLayout(LayoutKind.Sequential)]
  public struct DATA_BLOB { public int cbData; public IntPtr pbData; }

  public static byte[] Unprotect(byte[] blob, byte[] entropy) {
    DATA_BLOB inB = new DATA_BLOB();
    DATA_BLOB entB = new DATA_BLOB();
    DATA_BLOB outB = new DATA_BLOB();
    GCHandle h1 = GCHandle.Alloc(blob, GCHandleType.Pinned);
    GCHandle h2 = default(GCHandle);
    try {
      inB.cbData = blob.Length;
      inB.pbData = h1.AddrOfPinnedObject();
      if (entropy != null && entropy.Length > 0) {
        h2 = GCHandle.Alloc(entropy, GCHandleType.Pinned);
        entB.cbData = entropy.Length;
        entB.pbData = h2.AddrOfPinnedObject();
      }
      bool ok = CryptUnprotectData(ref inB, IntPtr.Zero, ref entB, IntPtr.Zero, IntPtr.Zero, 0, ref outB);
      if (!ok) return null;
      byte[] res = new byte[outB.cbData];
      Marshal.Copy(outB.pbData, res, 0, outB.cbData);
      LocalFree(outB.pbData);
      return res;
    } catch { return null; }
    finally {
      if (h1.IsAllocated) h1.Free();
      if (h2.IsAllocated) h2.Free();
    }
  }
}
'@
if (-not ('Dp' -as [type])) { Add-Type -TypeDefinition $code -Language CSharp }

$entropySets = @()
$entropySets += ,$null
if ($Entropy -ne "") {
  $entropySets += ,[Text.Encoding]::UTF8.GetBytes($Entropy)
  $entropySets += ,[Text.Encoding]::Unicode.GetBytes($Entropy)
  $entropySets += ,[Text.Encoding]::ASCII.GetBytes($Entropy)
}

$exts = @('.bin', '.dat', '.key', '.blob', '.enc', '.db', '.cfg', '.json')
$files = @()
foreach ($r in $Root) {
  if (-not (Test-Path -LiteralPath $r)) { continue }
  $files += Get-ChildItem -LiteralPath $r -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $exts -contains $_.Extension.ToLower() -and $_.Length -le $MaxSize -and $_.Length -ge 16 }
}

Write-Host ("roots  : " + ($Root -join ' ; '))
Write-Host ("blobs  : " + $files.Count)
if ($Entropy -ne "") { Write-Host ("entropy: '" + $Entropy + "' (trying none / utf8 / utf16le / ascii)") }
Write-Host ""

$cands = New-Object System.Collections.Generic.List[string]
$decrypted = 0

foreach ($f in $files) {
  $bytes = $null
  try { $bytes = [IO.File]::ReadAllBytes($f.FullName) } catch { continue }
  foreach ($ent in $entropySets) {
    $plain = [Dp]::Unprotect($bytes, $ent)
    if ($null -eq $plain -or $plain.Length -lt 8) { continue }
    $decrypted++
    $encName = if ($null -eq $ent) { 'none' } elseif ($ent.Length -eq 0) { 'empty' } else { 'ent' + $ent.Length }
    Write-Host ("[ok] " + $f.FullName + "  (" + $bytes.Length + " B, entropy=" + $encName + " -> " + $plain.Length + " B)")

    if ($plain.Length -eq 32) {
      $cands.Add((($plain | ForEach-Object { $_.ToString('x2') }) -join ''))
    }
    if ($AllWindows -or $plain.Length -ne 32) {
      for ($i = 0; $i + 32 -le $plain.Length; $i++) {
        $cands.Add((($plain[$i..($i + 31)] | ForEach-Object { $_.ToString('x2') }) -join ''))
      }
    }
    $utf8 = [Text.Encoding]::UTF8.GetString($plain)
    $shown = $utf8 -replace '[^\x20-\x7E]', '.'
    if ($shown.Length -gt 80) { $shown = $shown.Substring(0, 80) }
    Write-Host ("     text: " + $shown)
    break
  }
}

$uniq = $cands | Select-Object -Unique
[IO.File]::WriteAllLines($Out, $uniq)
Write-Host ""
Write-Host ("decrypted blobs : " + $decrypted)
Write-Host ("candidates      : " + $uniq.Count + "  -> " + $Out)
Write-Host ""
Write-Host "next:"
Write-Host ('  node verify-cands.js --pak="<your.pak>" "' + $Out + '"')
