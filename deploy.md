From the host:

```
SLAVENAME=pw-slave-cp313-01

ssh $SLAVENAME "echo '$SLAVENAME' > /etc/hostname"
scp piwheels.conf $SLAVENAME:/etc/
scp deploy*.sh $SLAVENAME:
scp check-disk-space.sh $SLAVENAME:/usr/local/bin/
scp piwheels-slave-check-disk-space* $SLAVENAME:/etc/systemd/system/
ssh $SLAVENAME "systemctl daemon-reload"
ssh $SLAVENAME "systemctl enable --now piwheels-slave-check-disk-space.timer"
```
