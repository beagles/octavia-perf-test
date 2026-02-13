# DevStack Troubleshooting Guide

## Recent Fixes Applied

The following fixes were just applied to `vagrant/scripts/bootstrap-controller.sh`:

1. **Added explicit OVS services**: `ovs-vswitchd` and `ovsdb-server`
2. **Fixed OVN metadata agent service name**: Changed from `networking-ovn-metadata-agent` to `q-ovn-metadata-agent`
3. **Added provider network configuration**: `OVN_BRIDGE_MAPPINGS=public:br-ex`
4. **Increased service timeouts**: `SERVICE_TIMEOUT=180` for slower VMs
5. **Enabled verbose logging**: `VERBOSE=True` for better debugging
6. **Fixed pip issues**: `PIP_UPGRADE=True`
7. **Disabled IPv6**: `IP_VERSION=4` and `SERVICE_IP_VERSION=4` to avoid RTNETLINK permission denied errors

## Steps to Fix and Re-run

### 1. Destroy and rebuild the controller VM with the fixes:

```bash
cd vagrant
vagrant destroy controller -f
vagrant up controller
```

### 2. SSH into the controller and check the bootstrap:

```bash
vagrant ssh controller
```

### 3. Inside the controller VM, verify the local.conf was created:

```bash
sudo cat /opt/stack/devstack/local.conf
```

Look for the new OVN settings:
- `enable_service ovs-vswitchd`
- `enable_service ovsdb-server`
- `enable_service q-ovn-metadata-agent`
- `OVN_BRIDGE_MAPPINGS=public:br-ex`

### 4. Run DevStack:

```bash
sudo -u stack /opt/stack/run_devstack.sh
```

This will take 30-60 minutes. Monitor for errors.

### 5. If it still fails, check the logs:

```bash
# Watch the log in real-time
sudo tail -f /opt/stack/logs/stack.sh.log

# After failure, check for errors
sudo grep -i 'error\|fail' /opt/stack/logs/stack.sh.log | tail -50

# Check specific service logs
ls -la /opt/stack/logs/
```

## Common Failure Scenarios

### IPv6 RTNETLINK Permission Denied

**Symptom**: DevStack fails with error: `RTNETLINK answers: Permission denied` when running `sudo ip -6 addr replace 2001:db8::2/64 dev br-ex`

**Root Cause**: IPv6 is disabled in the VM kernel or not properly configured. This is common in Vagrant VMs.

**Quick Fix Option 1 - Use the automated fix script**:
```bash
# On your host machine (not in the VM)
./fix_ipv6_issue.sh
```

**Quick Fix Option 2 - Manual fix** (if already inside the controller VM):
```bash
# SSH into controller
vagrant ssh controller

# Edit the local.conf
sudo vi /opt/stack/devstack/local.conf

# Add these lines after the [[local|localrc]] section (before LOGFILE):
# Disable IPv6 (not needed for perf testing)
IP_VERSION=4
SERVICE_IP_VERSION=4

# Clean up and re-run
cd /opt/stack/devstack
sudo -u stack ./unstack.sh
sudo -u stack ./clean.sh
sudo -u stack ./stack.sh
```

**Alternative - Enable IPv6 in the VM** (not recommended for this use case):
```bash
# Check if IPv6 is disabled
cat /proc/sys/net/ipv6/conf/all/disable_ipv6

# If it returns 1, IPv6 is disabled. Enable it:
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
sudo sysctl -w net.ipv6.conf.default.disable_ipv6=0

# Make it persistent
echo "net.ipv6.conf.all.disable_ipv6 = 0" | sudo tee -a /etc/sysctl.conf
echo "net.ipv6.conf.default.disable_ipv6 = 0" | sudo tee -a /etc/sysctl.conf

# Re-run DevStack
sudo -u stack /opt/stack/run_devstack.sh
```

### OVN Services Not Starting

**Symptom**: Errors about ovn-northd or ovn-controller not running

**Check**:
```bash
sudo systemctl status ovn-northd
sudo systemctl status ovn-controller
sudo ovn-nbctl show  # Should show OVN northbound DB
sudo ovn-sbctl show  # Should show OVN southbound DB
```

**Fix**: The updated bootstrap script should handle this, but if needed:
```bash
sudo apt install -y ovn-central ovn-host ovn-common
sudo systemctl restart ovn-central
sudo systemctl restart ovn-controller
```

### Neutron API Service Fails

**Symptom**: q-svc fails to start

**Check**:
```bash
sudo journalctl -u devstack@q-svc -n 100
```

**Common causes**:
- Database migration issues
- Port 9696 already in use
- OVN northbound DB not accessible

### Octavia Fails to Download Amphora Image

**Symptom**: Errors about downloading amphora image or creating amphora image in Glance

**Check**:
```bash
# Check if Glance is running
curl http://192.168.100.10:9292/versions

# Check amphora image download
ls -la /opt/stack/data/octavia/
```

**Fix**: Set explicit image URL in local.conf:
```bash
# Add to [[local|localrc]] section:
OCTAVIA_AMP_IMAGE_FILE=/tmp/amphora-x64-haproxy.qcow2
OCTAVIA_AMP_IMAGE_SIZE=3
```

### Port Conflicts

**Symptom**: Error about port already in use

**Check**:
```bash
sudo netstat -tulpn | grep -E ':(5555|9696|8774|8776|5000|35357)'
```

**Fix**: Kill the conflicting process or change the port in local.conf

### Memory/Resource Issues

**Symptom**: Services crash or timeout during startup

**Check**:
```bash
free -h
df -h
top
```

**Fix**: Increase VM memory in `vagrant/config.yaml`:
```yaml
controller:
  memory: 8192  # Try 12288 or 16384
  cpus: 4       # Try 6 or 8
```

## Network Configuration Validation

After DevStack completes successfully, verify the network setup:

```bash
# Source admin credentials
source /opt/stack/devstack/openrc admin admin

# Check OVN is working
sudo ovn-nbctl show
sudo ovn-sbctl show

# Check neutron networks
openstack network list
openstack subnet list

# Verify the public network was created
openstack network show public

# Check OVS bridges
sudo ovs-vsctl show
```

Expected bridges:
- `br-int` - Integration bridge for VM traffic
- `br-ex` - External bridge for provider/public network
- `br-mgmt` (created by Octavia) - Management network for amphora

## Next Steps After Successful Controller Stack

1. **Verify Octavia services are running**:
```bash
source /opt/stack/devstack/openrc admin admin
openstack loadbalancer list  # Should return empty, not error
```

2. **Set up compute nodes** (if using multi-node):
```bash
# On your host
cd vagrant
vagrant up compute-1

# SSH into compute-1
vagrant ssh compute-1

# Run DevStack on compute
sudo -u stack /opt/stack/run_devstack.sh

# Back on controller, discover the new compute host
vagrant ssh controller
cd /opt/stack/devstack
./tools/discover_hosts.sh
```

3. **Create test load balancer**:
```bash
# See the test creation scripts in the project
```

## If All Else Fails

### Use DevStack on Ubuntu 22.04 instead of 24.04

If you're using Ubuntu 24.04 (Noble), there may be compatibility issues. Try Ubuntu 22.04 (Jammy):

Edit `vagrant/config.yaml`:
```yaml
vms:
  controller:
    box: "generic/ubuntu2204"  # Ensure this is set
```

### Use stable branch instead of master

Edit `vagrant/config.yaml`:
```yaml
openstack:
  devstack_branch: "stable/2024.2"  # Or stable/2024.1
```

### Enable legacy Neutron agents as fallback

If OVN is problematic, fall back to ML2/OVS (edit bootstrap-controller.sh):
```bash
# Comment out OVN config
# Q_AGENT=ovn
# enable_service ovn-northd
# ...etc

# Enable instead:
enable_service q-agt
enable_service q-l3
enable_service q-dhcp
enable_service q-meta
```

## Getting More Help

Post the error logs with context:
1. Last 100 lines of `/opt/stack/logs/stack.sh.log`
2. Specific service log from `/opt/stack/logs/`
3. Output of `sudo systemctl status ovn-northd ovn-controller`
4. Output of `sudo ovs-vsctl show`
