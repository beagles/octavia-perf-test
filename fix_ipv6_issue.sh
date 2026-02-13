#!/bin/bash
# Fix IPv6 issue in existing controller VM
# Run this on your HOST machine (not inside the VM)

set -e

echo "=== Fixing IPv6 issue in DevStack ==="
echo ""
echo "This will update the DevStack local.conf on the controller VM to disable IPv6"
echo ""

# Create the fix script to run inside the VM
cat > /tmp/fix_devstack_ipv6.sh << 'VMSCRIPT'
#!/bin/bash
set -e

echo "Checking if DevStack local.conf exists..."
if [ ! -f /opt/stack/devstack/local.conf ]; then
    echo "ERROR: /opt/stack/devstack/local.conf not found!"
    exit 1
fi

echo "Backing up local.conf..."
sudo cp /opt/stack/devstack/local.conf /opt/stack/devstack/local.conf.backup

echo "Adding IPv6 disable settings to local.conf..."
sudo sed -i '/^LOGFILE=/i \
# Disable IPv6 (not needed for perf testing, causes issues in VMs)\
IP_VERSION=4\
SERVICE_IP_VERSION=4\
' /opt/stack/devstack/local.conf

echo ""
echo "Updated local.conf. Showing the new settings:"
grep -A2 "Disable IPv6" /opt/stack/devstack/local.conf || echo "Settings added before LOGFILE line"

echo ""
echo "Cleaning up any failed DevStack run..."
if [ -f /opt/stack/devstack/unstack.sh ]; then
    cd /opt/stack/devstack
    sudo -u stack ./unstack.sh || true
    sudo -u stack ./clean.sh || true
fi

echo ""
echo "=== Fix complete! ==="
echo ""
echo "Now run DevStack again:"
echo "  sudo -u stack /opt/stack/run_devstack.sh"
echo ""
echo "Or if you want to clean everything and start fresh:"
echo "  cd /opt/stack/devstack"
echo "  sudo -u stack ./clean.sh"
echo "  sudo -u stack ./stack.sh"
VMSCRIPT

# Copy script to VM and execute it
echo "Copying fix script to controller VM..."
cd vagrant
vagrant upload /tmp/fix_devstack_ipv6.sh /tmp/fix_devstack_ipv6.sh controller

echo "Running fix on controller VM..."
vagrant ssh controller -c "chmod +x /tmp/fix_devstack_ipv6.sh && sudo -u stack /tmp/fix_devstack_ipv6.sh"

echo ""
echo "=== Done! ==="
echo ""
echo "Now SSH into the controller and run DevStack:"
echo "  cd vagrant && vagrant ssh controller"
echo "  sudo -u stack /opt/stack/run_devstack.sh"
