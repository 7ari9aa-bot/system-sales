import { useState } from "react";
import { Button } from "@/applications/apparel/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/applications/apparel/components/ui/dialog";
import { useT } from "@/lib/i18n";
import { receiptBytes } from "@/applications/apparel/lib/receiptPrint";
import { printerErrorKey } from "@/applications/apparel/lib/printerErrors";
import {
  connectBluetoothPrinter,
  connectUsbPrinter,
  disconnectPrinter,
  getConnectedPrinterName,
  isPrinterConnected,
  isWebBluetoothSupported,
  isWebUsbSupported,
  kickCashDrawer,
  printRaw,
} from "@/applications/apparel/lib/printerBridge";

export default function PrinterSetupDialog({ open, onOpenChange }) {
  const t = useT();
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  // Closing the device picker is not a failure; anything else is shown in the shop's language.
  const failureText = (err, action) => {
    const key = printerErrorKey(err, action);
    return key ? t(key) : "";
  };

  const connected = isPrinterConnected();
  const printerName = getConnectedPrinterName();

  const handleConnectUsb = async () => {
    setErrorMsg("");
    setStatusMsg("");
    setLoading(true);
    try {
      const res = await connectUsbPrinter();
      setStatusMsg(t("pos.printer.connected").replace("{name}", res.name));
    } catch (err) {
      setErrorMsg(failureText(err, "connectUsb"));
    } finally {
      setLoading(false);
    }
  };

  const handleConnectBt = async () => {
    setErrorMsg("");
    setStatusMsg("");
    setLoading(true);
    try {
      const res = await connectBluetoothPrinter();
      setStatusMsg(t("pos.printer.connected").replace("{name}", res.name));
    } catch (err) {
      setErrorMsg(failureText(err, "connectBluetooth"));
    } finally {
      setLoading(false);
    }
  };

  const handleTestPrint = async () => {
    setErrorMsg("");
    setLoading(true);
    try {
      const testBytes = receiptBytes({
        shopName: "فهرست - اختبار الطباعة",
        receiptNumber: "TEST-0001",
        items: [
          { name: "صنف تجريبي ١", quantity: 1, unit_price: "10.00", total: "10.00" },
          { name: "صنف تجريبي ٢", quantity: 2, unit_price: "20.00", total: "40.00" },
        ],
        total: "50.00",
        footerNote: "نجح اختبار الطابعة",
      });
      await printRaw(testBytes);
      setStatusMsg(t("pos.printer.printSuccess"));
    } catch (err) {
      setErrorMsg(failureText(err, "testPrint"));
    } finally {
      setLoading(false);
    }
  };

  const handleKickDrawer = async () => {
    setErrorMsg("");
    setLoading(true);
    try {
      await kickCashDrawer();
      setStatusMsg("تم إرسال إشارة فتح الدرج بنجاح.");
    } catch (err) {
      setErrorMsg(failureText(err, "kick"));
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    await disconnectPrinter();
    setStatusMsg("");
    setErrorMsg("");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{t("pos.printer.title")}</DialogTitle>
          <DialogDescription>
            {connected
              ? t("pos.printer.connected").replace("{name}", printerName)
              : t("pos.printer.notConnected")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {errorMsg ? (
            <p role="alert" className="text-xs font-semibold text-rose-600 bg-rose-50 dark:bg-rose-950/30 p-2 rounded">
              {errorMsg}
            </p>
          ) : null}

          {statusMsg ? (
            <p className="text-xs font-semibold text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 p-2 rounded">
              {statusMsg}
            </p>
          ) : null}

          {!connected ? (
            <div className="space-y-2">
              <Button
                type="button"
                className="w-full font-semibold"
                onClick={handleConnectUsb}
                disabled={loading || !isWebUsbSupported()}
              >
                {t("pos.printer.connectUsb")} {!isWebUsbSupported() ? "(غير مدعوم)" : ""}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full font-semibold"
                onClick={handleConnectBt}
                disabled={loading || !isWebBluetoothSupported()}
              >
                {t("pos.printer.connectBluetooth")} {!isWebBluetoothSupported() ? "(غير مدعوم)" : ""}
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={handleTestPrint}
                  disabled={loading}
                >
                  {t("pos.printer.testPrint")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={handleKickDrawer}
                  disabled={loading}
                >
                  {t("pos.printer.kickDrawer")}
                </Button>
              </div>
              <Button
                type="button"
                variant="ghost"
                className="w-full text-rose-600 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/30"
                onClick={handleDisconnect}
                disabled={loading}
              >
                فصل الطابعة
              </Button>
            </div>
          )}
        </div>

        <div className="flex justify-end pt-2 border-t border-slate-200 dark:border-slate-800">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            إغلاق
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
