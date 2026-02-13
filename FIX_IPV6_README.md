# IPv6 RTNETLINK Permission Denied - Fix Guide

## Problem
DevStack is failing with:
```
RTNETLINK answers: Permission denied
```
When trying to configure IPv6 on br-ex bridge.

## Solution
Since this is a performance testing framework for IPv4 load balancing, we don't need IPv6. The fix is to disable IPv6 in DevStack.

---

## Option 1: Automated Fix (Recommended)

Run this script from your **host machine** (not inside the VM):

```bash
./fix_ipv6_issue.sh
```

This will:
1. Update the DevStack local.conf on your controller VM
2. Add `IP_VERSION=4` and `SERVICE_IP_VERSION=4` settings
3. Clean up any failed DevStack runs

Then SSH into the controller and re-run DevStack:
```bash
cd vagrant
vagrant ssh controller
sudo -u stack /opt/stack/run_devstack.sh
```

---

## Option 2: Manual Fix (if script doesn't work)

### Step 1: SSH into the controller
```bash
cd vagrant
vagrant ssh controller
```

### Step 2: Edit the DevStack configuration
```bash
sudo nano /opt/stack/devstack/local.conf
```

### Step 3: Add these lines near the top (after `[[local|localrc]]`, before `HOST_IP`):
```bash
# Disable IPv6 (not needed for perf testing, causes issues in VMs)
IP_VERSION=4
SERVICE_IP_VERSION=4
```

### Step 4: Save the file (Ctrl+O, Enter, Ctrl+X in nano)

### Step 5: Clean up and re-run DevStack
```bash
cd /opt/stack/devstack

# Clean up failed run
sudo -u stack ./unstack.sh || true
sudo -u stack ./clean.sh || true

# Run DevStack again
sudo -u stack ./stack.sh
```

---

## Option 3: Rebuild VM with Fix (Clean Slate)

The bootstrap scripts have already been updated with the IPv6 fix. To start fresh:

```bash
cd vagrant
vagrant destroy controller -f
vagrant up controller
vagrant ssh controller
sudo -u stack /opt/stack/run_devstack.sh
```

---

## Verification

After DevStack completes successfully, verify it's working:

```bash
# Inside the controller VM
source /opt/stack/devstack/openrc admin admin

# Should work without errors:
openstack network list
openstack service list
openstack loadbalancer list
```

---

## If You Still Get Errors

Check the full logs:
```bash
sudo tail -100 /opt/stack/logs/stack.sh.log
```

Look for other errors unrelated to IPv6. Common issues:
- OVN services not starting
- Port conflicts
- Memory/resource constraints
- Download timeouts

See `DEVSTACK_TROUBLESHOOTING.md` for more help.
