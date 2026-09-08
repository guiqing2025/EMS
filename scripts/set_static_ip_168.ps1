# Set this PC Ethernet to static IP 192.168.2.168
# Run as Administrator AFTER the old 192.168.2.168 machine is offline.
# Usage:
#   Set-ExecutionPolicy -Scope Process Bypass
#   C:\EMS\scripts\set_static_ip_168.ps1

$ErrorActionPreference = "Stop"
$IfIndex = 8
$IP = "192.168.2.168"
$Prefix = 24
$Gateway = "192.168.2.1"
$Dns = @("202.96.128.86", "202.96.134.33")

Write-Host "Checking whether $IP is free..."
$ping = Test-Connection -ComputerName $IP -Count 1 -Quiet -ErrorAction SilentlyContinue
$myIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress)
if ($ping -and ($myIps -notcontains $IP)) {
    Write-Host "REFUSED: $IP is already used by another device on the LAN."
    Write-Host "Please power off / change IP of that machine first, then rerun this script."
    exit 2
}

Write-Host "Removing old IPv4 addresses on interface $IfIndex..."
Get-NetIPAddress -InterfaceIndex $IfIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '169.254.*' } |
    ForEach-Object {
        Remove-NetIPAddress -InterfaceIndex $IfIndex -IPAddress $_.IPAddress -Confirm:$false -ErrorAction SilentlyContinue
    }

Get-NetRoute -InterfaceIndex $IfIndex -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "Setting static $IP/$Prefix gateway $Gateway ..."
New-NetIPAddress -InterfaceIndex $IfIndex -IPAddress $IP -PrefixLength $Prefix -DefaultGateway $Gateway | Out-Null
Set-DnsClientServerAddress -InterfaceIndex $IfIndex -ServerAddresses $Dns
Set-NetIPInterface -InterfaceIndex $IfIndex -Dhcp Disabled -ErrorAction SilentlyContinue

Start-Sleep -Seconds 2
ipconfig | Select-String -Pattern "IPv4|Subnet|Gateway" 
Write-Host "Done. Next start EMS:"
Write-Host "  C:\EMS\start_local_windows.ps1 -Force"
Write-Host "Colleague URL: http://192.168.2.168:8888"
