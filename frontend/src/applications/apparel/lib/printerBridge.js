import { PrinterError } from "./printerErrors";
/**
 * Hardware printer bridge for ESC/POS thermal printers.
 * Supports WebUSB and WebBluetooth interfaces with automatic endpoint resolution.
 */

import { COMMANDS } from "./escpos";

let activeUsbDevice = null;
let activeBtCharacteristic = null;
let printerType = null; // "usb" | "bluetooth" | null

export function isWebUsbSupported() {
  return typeof navigator !== "undefined" && Boolean(navigator.usb);
}

export function isWebBluetoothSupported() {
  return typeof navigator !== "undefined" && Boolean(navigator.bluetooth);
}

export function isPrinterConnected() {
  return Boolean(activeUsbDevice || activeBtCharacteristic);
}

export function getConnectedPrinterName() {
  if (activeUsbDevice) {
    return activeUsbDevice.productName || "USB Thermal Printer";
  }
  if (activeBtCharacteristic) {
    return "Bluetooth Thermal Printer";
  }
  return null;
}

/**
 * Connects to a USB ESC/POS printer via WebUSB.
 */
export async function connectUsbPrinter() {
  if (!isWebUsbSupported()) {
    throw new PrinterError("usb_unsupported");
  }

  // Common thermal printer USB class is 7 (Printer) or vendor-specific
  const device = await navigator.usb.requestDevice({
    filters: [
      { classCode: 7 }, // Printer class
    ],
  });

  await device.open();
  if (device.configuration === null) {
    await device.selectConfiguration(1);
  }

  // Find interface with bulk OUT endpoint
  let interfaceNumber = 0;
  let endpointNumber = 1;

  for (const conf of device.configurations) {
    for (const intf of conf.interfaces) {
      for (const alt of intf.alternates) {
        const outEndpoint = alt.endpoints.find((ep) => ep.direction === "out" && ep.type === "bulk");
        if (outEndpoint) {
          interfaceNumber = intf.interfaceNumber;
          endpointNumber = outEndpoint.endpointNumber;
          break;
        }
      }
    }
  }

  await device.claimInterface(interfaceNumber);
  device._claimedInterfaceNumber = interfaceNumber;
  device._endpointOut = endpointNumber;

  activeUsbDevice = device;
  printerType = "usb";

  return {
    name: device.productName || "USB Thermal Printer",
    vendorId: device.vendorId,
    productId: device.productId,
  };
}

/**
 * Connects to a Bluetooth ESC/POS printer via WebBluetooth.
 */
export async function connectBluetoothPrinter() {
  if (!isWebBluetoothSupported()) {
    throw new PrinterError("bt_unsupported");
  }

  // Standard SPP/Serial port services for bluetooth thermal printers
  const device = await navigator.bluetooth.requestDevice({
    acceptAllDevices: true,
    optionalServices: [
      "000018f0-0000-1000-8000-00805f9b34fb",
      "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
      "49535343-fe7d-4ae5-8fa9-9fafd205e455",
    ],
  });

  const server = await device.gatt.connect();
  const services = await server.getPrimaryServices();

  let writeCharacteristic = null;
  for (const service of services) {
    const characteristics = await service.getCharacteristics();
    writeCharacteristic = characteristics.find(
      (c) => c.properties.write || c.properties.writeWithoutResponse,
    );
    if (writeCharacteristic) break;
  }

  if (!writeCharacteristic) {
    throw new PrinterError("no_characteristic");
  }

  activeBtCharacteristic = writeCharacteristic;
  printerType = "bluetooth";

  return {
    name: device.name || "Bluetooth Thermal Printer",
  };
}

/**
 * Sends raw bytes to the connected printer.
 * @param {Uint8Array} data
 */
export async function printRaw(data) {
  if (activeUsbDevice) {
    const endpoint = activeUsbDevice._endpointOut || 1;
    // Chunking to 64 bytes for USB endpoint packet safety
    const chunkSize = 64;
    for (let i = 0; i < data.length; i += chunkSize) {
      const chunk = data.slice(i, i + chunkSize);
      await activeUsbDevice.transferOut(endpoint, chunk);
    }
    return;
  }

  if (activeBtCharacteristic) {
    // BLE characteristic MTU is typically 20-512 bytes; send in 64-byte chunks
    const chunkSize = 64;
    for (let i = 0; i < data.length; i += chunkSize) {
      const chunk = data.slice(i, i + chunkSize);
      if (activeBtCharacteristic.properties.writeWithoutResponse) {
        await activeBtCharacteristic.writeValueWithoutResponse(chunk);
      } else {
        await activeBtCharacteristic.writeValue(chunk);
      }
    }
    return;
  }

  throw new PrinterError("not_connected");
}

/**
 * Sends a cash drawer kick command to the connected printer.
 */
export async function kickCashDrawer() {
  await printRaw(COMMANDS.DRAWER_KICK);
}

/**
 * Disconnects the active printer.
 */
export async function disconnectPrinter() {
  if (activeUsbDevice) {
    try {
      if (activeUsbDevice._claimedInterfaceNumber !== undefined) {
        await activeUsbDevice.releaseInterface(activeUsbDevice._claimedInterfaceNumber);
      }
      await activeUsbDevice.close();
    } catch {
      // non-fatal
    }
    activeUsbDevice = null;
  }

  if (activeBtCharacteristic) {
    try {
      activeBtCharacteristic.service?.device?.gatt?.disconnect();
    } catch {
      // non-fatal
    }
    activeBtCharacteristic = null;
  }

  printerType = null;
}
