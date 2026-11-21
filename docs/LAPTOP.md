# desk-hub: the Samba share

desk-hub only stores files for wt-analytics; no processing runs there, so Klipper is never
starved. Samba uses a few tens of MB of RAM and no CPU while idle. Nothing in the desk-hub
project itself changes. Everything below runs over SSH (`ssh deskhub@deskhub.local`).

No IP addresses anywhere: the PC connects to `deskhub.local`, and the share accepts only private
home-network addresses (`192.168.x.x`, `10.x.x.x`, `172.16–31.x.x`), which never change and can't
come from the internet.

## 1. Look before changing anything
Disks and free space — pick the big one for the share:
```bash
df -h -x tmpfs -x devtmpfs
```
Is Samba already installed or in use (if this prints shares, tell Claude before going on)?
```bash
systemctl is-active smbd; testparm -s 2>/dev/null | grep '^\['
```

## 2. Install and create the share
Set the folder on the big disk first (same SSH session):
```bash
WT_DIR=/srv/wt
```
Install Samba (small; does not touch Klipper):
```bash
sudo apt update && sudo apt install -y samba
```
A login-less system user that owns the files:
```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin wtshare
```
Its Samba password (you type it twice; the PC uses it to connect):
```bash
sudo smbpasswd -a wtshare
```
The folder:
```bash
sudo mkdir -p "$WT_DIR" && sudo chown wtshare:wtshare "$WT_DIR" && sudo chmod 750 "$WT_DIR"
```
Back up the config, then add the share (LAN only, no guests, SMB3 or newer):
```bash
sudo cp -n /etc/samba/smb.conf /etc/samba/smb.conf.before-wt
```
```bash
printf '\n[wt]\n   path = %s\n   valid users = wtshare\n   force user = wtshare\n   read only = no\n   browseable = no\n   guest ok = no\n   create mask = 0640\n   directory mask = 0750\n   server min protocol = SMB3\n   hosts allow = 127.0.0.1 192.168. 10. 172.16.0.0/12\n   hosts deny = 0.0.0.0/0\n' "$WT_DIR" | sudo tee -a /etc/samba/smb.conf
```
Check it (must print no errors, and a `[wt]` section):
```bash
testparm -s 2>&1 | sed -n '/^\[wt\]/,$p'
```
Start it now and at boot:
```bash
sudo systemctl enable --now smbd && sudo systemctl restart smbd
```
If the firewall is on (`sudo ufw status` says active), allow Samba from home networks only:
```bash
for net in 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12; do sudo ufw allow from $net to any app Samba; done
```
Test the login locally (enter the `wtshare` password; should print `.` and `..`):
```bash
smbclient //localhost/wt -U wtshare -c ls
```
(`sudo apt install -y smbclient` first if it is missing.)

## 3. On the gaming PC (Windows 11)
In a Command Prompt; it asks for the `wtshare` password (not the SSH one). Use the name, not the
IP, so a changed address doesn't matter:
```bash
net use W: \\deskhub.local\wt /user:wtshare /persistent:yes
```
If `W:` ever fails to reconnect after a reboot, give desk-hub a fixed address in the router's DHCP
settings (keep using the name).
`W:` then appears in Explorer. In the helper's config: `share = "W:/"` — it creates `raw`,
`decoded` and `manifest` itself. If the share is offline, battles wait in the helper's staging
folder and are copied later.

## Undo
```bash
sudo cp /etc/samba/smb.conf.before-wt /etc/samba/smb.conf && sudo systemctl restart smbd
```

## Disk space
~50–70 MB per battle (raw + decoded). Check with `df -h "$WT_DIR"` (or `df -h /srv/wt`).
