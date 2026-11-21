# desk-hub: the Samba share

desk-hub only stores files for wt-analytics. It runs no wt-analytics processing, so Klipper is
never starved. Samba's own use is small (tens of MB of RAM, idle CPU when nothing is copied).
This does not change the desk-hub project itself.

## 1. On desk-hub (Ubuntu Server)
Replace `192.168.1.0/24` with your LAN, and `/srv/wt` with wherever the big disk is mounted.

```bash
sudo apt update && sudo apt install -y samba
```

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin wtshare
```

```bash
sudo smbpasswd -a wtshare
```

```bash
sudo mkdir -p /srv/wt && sudo chown wtshare:wtshare /srv/wt && sudo chmod 750 /srv/wt
```

Add this share to the end of `/etc/samba/smb.conf` (`sudo nano /etc/samba/smb.conf`):

```ini
[wt]
   path = /srv/wt
   valid users = wtshare
   force user = wtshare
   read only = no
   browseable = no
   guest ok = no
   create mask = 0640
   directory mask = 0750
   hosts allow = 127.0.0.1 192.168.1.0/24
   hosts deny = 0.0.0.0/0
```

And in the `[global]` section, make sure these lines are present (LAN only, modern protocol):

```ini
   server min protocol = SMB3
   map to guest = never
   interfaces = lo 192.168.1.0/24
   bind interfaces only = yes
```

Check the config and restart:

```bash
testparm -s
```

```bash
sudo systemctl restart smbd && sudo systemctl enable smbd
```

If `ufw` is on, allow Samba from the LAN only:

```bash
sudo ufw allow from 192.168.1.0/24 to any app Samba
```

## 2. On the gaming PC (Windows 11)
Map the share as `W:` (replace `desk-hub` with its hostname or IP). It asks for the
`wtshare` password; tick "Remember my credentials".

```bash
net use W: \\desk-hub\wt /user:wtshare /persistent:yes
```

Then in the helper's config: `share = "W:/"` — the helper creates `raw`, `decoded` and
`manifest` in it itself. If the share is offline, the helper keeps battles in its staging folder and
copies them later.

## 3. Disk space
Expect ~50–70 MB per battle (raw + decoded). Check free space on desk-hub with `df -h /srv/wt`.
