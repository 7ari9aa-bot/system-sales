import { useNavigate } from "react-router-dom";
import { Barcode, MoreHorizontal, PenSquare } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/cashier/components/ui/dropdown-menu";

// إجراءات صف المنتج: عرض/تعديل وطباعة ملصقات الباركود.
export default function ProductRowActions({ product, onLabels }) {
  const navigate = useNavigate();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`إجراءات ${product.name}`}>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56" dir="rtl">
        <DropdownMenuLabel className="truncate text-xs text-muted-foreground">{product.name}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="gap-2"
          onSelect={() => navigate(`/cashier/products/${product.id}/edit`)}
        >
          <PenSquare className="h-4 w-4" />
          عرض وتعديل المنتج
        </DropdownMenuItem>
        <DropdownMenuItem className="gap-2" onSelect={onLabels}>
          <Barcode className="h-4 w-4" />
          طباعة ملصقات الباركود
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}