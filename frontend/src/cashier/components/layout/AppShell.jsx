import { useState } from "react";
import { Menu } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import AppSidebar from "@/cashier/components/layout/AppSidebar";

// الهيكل الموحّد لكل شاشات النظام: قائمة جانبية + مساحة عمل.
export default function AppShell({ children }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-row-reverse bg-background">
      <AppSidebar mobileOpen={menuOpen} onMobileOpenChange={setMenuOpen} />
      <div className="flex min-w-0 flex-1 flex-col">
        {/* زر فتح القائمة يظهر على الموبايل فقط */}
        <div className="flex h-11 items-center px-2 lg:hidden">
          <Button variant="ghost" size="icon" onClick={() => setMenuOpen(true)} aria-label="فتح القائمة">
            <Menu className="h-5 w-5" />
          </Button>
        </div>
        <main className="flex-1 px-2 py-2 sm:px-3">
          <div className="w-full">{children}</div>
        </main>
      </div>
    </div>
  );
}