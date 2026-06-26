"""
One-time pairing script for Apple TV.

Run this once:
    python tests/pair_appletv.py

Your Apple TV will show a PIN on screen.  Enter it when prompted.
Credentials are saved to appletv_credentials.json and loaded automatically
by appletv_device.py from then on.
"""
import asyncio
import json
import os
import sys

# Package root (parent of tests/) -- where the app reads/writes its files.
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Allow flat imports (config) when run from the tests/ subfolder.
sys.path.insert(0, _BASE)

# Credentials must land in the package root so appletv_device.py finds them.
CREDENTIALS_FILE = os.path.join(_BASE, "appletv_credentials.json")

try:
    import pyatv
    from pyatv.const import Protocol
except ImportError:
    print("pyatv not installed — run: pip install pyatv --break-system-packages")
    sys.exit(1)


async def main(ip: str) -> None:
    """Pair with the Apple TV via Companion and save the credentials.

    Parameters:
        - ip: The Apple TV's IP address to scan for and pair with.
    """
    loop = asyncio.get_running_loop()
    print(f"Scanning for Apple TV at {ip}…")
    devs = await pyatv.scan(loop, hosts=[ip], timeout=10)
    if not devs:
        print(f"No Apple TV found at {ip}. Check the IP and try again.")
        return

    conf = devs[0]
    print(f"Found: {conf.name}  (identifier: {conf.identifier})")

    svc = conf.get_service(Protocol.Companion)
    if svc is None:
        print("Companion protocol not available on this device.")
        return

    print("\nStarting Companion pairing…")
    pairing = await pyatv.pair(conf, Protocol.Companion, loop)
    await pairing.begin()

    if pairing.device_provides_pin:
        pin_str = input("Enter the PIN shown on your Apple TV: ").strip()
        pairing.pin(int(pin_str))
    else:
        print(f"Enter this PIN on your Apple TV: {pairing.pin}")
        input("Press Enter once you've accepted it on the TV… ")

    await pairing.finish()

    if pairing.has_paired:
        creds = conf.get_service(Protocol.Companion).credentials
        data = {}
        if os.path.exists(CREDENTIALS_FILE):
            with open(CREDENTIALS_FILE) as f:
                data = json.load(f)
        data["Companion"] = creds
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nPaired! Credentials saved to {CREDENTIALS_FILE}")
        print(f"Companion: {creds}")
    else:
        print("Pairing failed — wrong PIN?")

    await pairing.close()


if __name__ == "__main__":
    import config
    ip = getattr(config, "APPLETV_IP", "").strip()
    if not ip:
        ip = input("Enter Apple TV IP address: ").strip()
    asyncio.run(main(ip))
