param([Parameter(Mandatory=$true)][ValidateSet('stage1','stage2')][string]$Stage)
$ErrorActionPreference='Stop';$os=Get-CimInstance Win32_OperatingSystem
$admitRam=if($Stage -eq 'stage1'){5.5}else{6};$admitCommit=if($Stage -eq 'stage1'){5.5}else{6.5}
if (($os.FreePhysicalMemory/1MB -lt $admitRam) -or ($os.FreeVirtualMemory/1MB -lt $admitCommit)) { throw 'host admission below stage threshold' }
$admission=@{free_physical_gib=$os.FreePhysicalMemory/1MB;free_commit_gib=$os.FreeVirtualMemory/1MB}
$env:PYTHONDONTWRITEBYTECODE='1';$env:HF_HUB_OFFLINE='1';$env:OMP_NUM_THREADS='1';$env:OPENBLAS_NUM_THREADS='1'
$python=(Resolve-Path '.local-pilot/motor-amd-venv/Scripts/python.exe').Path;$out=(Resolve-Path '.local-pilot/scooter-stage-isolation-20261101').Path
$script=if($Stage -eq 'stage1'){'stage1_features.py'}else{'stage2_match.py'};$deadline=if($Stage -eq 'stage1'){120}else{420}
$p=Start-Process -FilePath $python -ArgumentList @('"'+(Join-Path $out $script)+'"') -RedirectStandardOutput (Join-Path $out "$Stage.stdout") -RedirectStandardError (Join-Path $out "$Stage.stderr") -WindowStyle Hidden -PassThru
$watch=[Diagnostics.Stopwatch]::StartNew();$peak=0;$private=0;$limit=$null;$minPhysical=[double]::MaxValue;$minCommit=[double]::MaxValue
while(-not $p.HasExited){
 $all=@(Get-CimInstance Win32_Process);$ids=@($p.Id);$old=0
 while($ids.Count -ne $old){$old=$ids.Count;$ids=@($ids+@($all|Where-Object {$_.ParentProcessId -in $ids}|ForEach-Object {$_.ProcessId})|Select-Object -Unique)}
 $bytes=0;$priv=0;foreach($id in $ids){$q=Get-Process -Id $id -ErrorAction SilentlyContinue;if($q){$bytes+=$q.WorkingSet64;$priv+=$q.PrivateMemorySize64}};if($bytes -gt $peak){$peak=$bytes};if($priv -gt $private){$private=$priv}
 $o=Get-CimInstance Win32_OperatingSystem;$ram=$o.FreePhysicalMemory/1MB;$commit=$o.FreeVirtualMemory/1MB
 if($ram -lt $minPhysical){$minPhysical=$ram};if($commit -lt $minCommit){$minCommit=$commit}
 if($ram -lt 4.5 -or $commit -lt 4.5){$limit='host_reserve_below_4.5GiB'}
 if($Stage -eq 'stage1' -and $priv -gt 768MB){$limit='stage1_private_commit_above_768MiB'}
 if($watch.Elapsed.TotalSeconds -gt $deadline){$limit='stage_deadline'}
 if($limit){foreach($id in $ids){Stop-Process -Id $id -Force -ErrorAction SilentlyContinue};break};Start-Sleep -Milliseconds 150
}
$p.WaitForExit();$watch.Stop();$r=[ordered]@{stage=$Stage;admission=$admission;wall_s=[math]::Round($watch.Elapsed.TotalSeconds,3);sampled_peak_tree_working_set_bytes=$peak;sampled_peak_tree_private_bytes=$private;minimum_sampled_free_physical_gib=$minPhysical;minimum_sampled_free_commit_gib=$minCommit;guard=$limit;exit_code=$p.ExitCode};$r|ConvertTo-Json -Depth 6|Set-Content (Join-Path $out "$Stage-watchdog.json") -Encoding utf8;$r|ConvertTo-Json -Depth 6
