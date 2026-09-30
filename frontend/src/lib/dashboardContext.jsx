import React, { createContext, useContext, useState } from "react";
import { DEFAULT_RANGE, LOCATIONS } from "@/lib/dashboardData";

const DashboardContext = createContext(null);

export function DashboardProvider({ children }) {
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [location, setLocation] = useState(LOCATIONS[0].id);

  return (
    <DashboardContext.Provider value={{ range, setRange, location, setLocation }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}