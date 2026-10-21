import { DatabaseBackup, Printer, Store, Tags, Users, Wallet } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/cashier/components/ui/tabs";
import PageHeader from "@/cashier/components/ui-kit/PageHeader";
import ShopProfileForm from "@/cashier/components/settings/ShopProfileForm";
import SalesSettings from "@/cashier/components/settings/SalesSettings";
import PrintAndBarcodeSettings from "@/cashier/components/settings/PrintAndBarcodeSettings";
import CategoriesSettings from "@/cashier/components/settings/CategoriesSettings";
import UsersSettings from "@/cashier/components/settings/UsersSettings";
import BackupTab from "@/cashier/components/settings/BackupTab";


const TABS = [
  { value: "shop", label: "بيانات المحل", icon: Store },
  { value: "sales", label: "المبيعات والخصم", icon: Wallet },
  { value: "print", label: "الطباعة والباركود", icon: Printer },
  { value: "lists", label: "الفئات", icon: Tags },
  { value: "users", label: "المستخدمون", icon: Users },
  { value: "backup", label: "النسخ الاحتياطي", icon: DatabaseBackup },
];

export default function SettingsPage() {
  return (
    <div className="animate-fade-up space-y-4">
      <PageHeader title="الإعدادات" description="بيانات المحل، طرق الدفع وحدود الخصم، الفاتورة والباركود، القوائم، المستخدمون، والنسخ الاحتياطي" />

      <Tabs defaultValue="shop" className="w-full">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-xl border border-border bg-card p-1.5">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <TabsTrigger
                key={t.value}
                value={t.value}
                className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-[12.5px] font-medium data-[state=active]:bg-[#E8761A] data-[state=active]:text-white data-[state=active]:shadow-sm"
              >
                <Icon className="h-4 w-4" />
                {t.label}
              </TabsTrigger>
            );
          })}
        </TabsList>

        <TabsContent value="shop" className="mt-4">
          <ShopProfileForm />
        </TabsContent>
        <TabsContent value="sales" className="mt-4">
          <SalesSettings />
        </TabsContent>
        <TabsContent value="print" className="mt-4">
          <PrintAndBarcodeSettings />
        </TabsContent>
        <TabsContent value="lists" className="mt-4">
          <CategoriesSettings />
        </TabsContent>
        <TabsContent value="users" className="mt-4">
          <UsersSettings />
        </TabsContent>
        <TabsContent value="backup" className="mt-4">
          <BackupTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}