# Trigger

My VPS is small and streamlit consumes a lot of RAM. I need to create a tunnel for remote MySQL access so that the backoffice can be run from my laptop.

# Create a Tunnel for remote MySQL

VPS : the remote server where the MySQL database is hosted. prod.xyz
DEV : the local development environment where the backoffice is run.

DEV:
sudo apt install -y default-libmysqlclient-dev build-essential pkg-config
pip install mysqlclient
pip install pymysql cryptography

VPS: 
sudo adduser --disabled-password --shell /bin/false tunnel_user
sudo mkdir -p /home/tunnel_user/.ssh
sudo chmod 700 /home/tunnel_user/.ssh

DEV: 
ssh-keygen -t ed25519 -f ~/.ssh/prod_tunnel_key -C "prod-db-tunnel"

VPS:
sudo nano /home/tunnel_user/.ssh/authorized_keys
restrict,port-forwarding,permitopen="127.0.0.1:3306",from="YOUR.LAPTOP.FIXED.IP" ssh-ed25519 AAAA...

VPS:
sudo ufw allow from YOUR.LAPTOP.FIXED.IP to any port 22

DEV : 
ssh -N -L 3307:127.0.0.1:3306 tunnel_user@prod.xyz -i ~/.ssh/prod_tunnel_key

local_config.json
{
  "database": {
    "path": "mysql+mysqldb://prod_user:prod_password@127.0.0.1:3307/prod_db"
  }
}

Add to your `~/.ssh/config` on the laptop:
```
Host prod-db-tunnel
    HostName prod.xyz
    User tunnel_user
    IdentityFile ~/.ssh/prod_tunnel_key
    LocalForward 3307 127.0.0.1:3306
    ServerAliveInterval 60
    ServerAliveCountMax 3
    ExitOnForwardFailure yes
    
background daemon : 
ssh -fN prod-db-tunnel

VPS: 
sudo chown -R tunnel_user:tunnel_user /home/tunnel_user/.ssh
sudo chmod 700 /home/tunnel_user/.ssh
sudo chmod 600 /home/tunnel_user/.ssh/authorized_keys

sudo nano /etc/ssh/sshd_config
AllowTcpForwarding yes
PermitOpen 127.0.0.1:3306
