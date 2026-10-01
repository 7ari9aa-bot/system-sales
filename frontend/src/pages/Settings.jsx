import React from "react";
import { PageHeader, SectionCard, Badge, ProgressBar } from "@/components/dashboard/ui";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { useRealUsage } from "@/hooks/useRealData";
import { CHANNELS } from "@/lib/channels";
import { User, Bell, Shield, Plug, CreditCard, Palette } from "lucide-react";

function Row({ icon: Icon, title, desc, children }) {
  return (
    <div className="flex items-center gap-4 py-4">
      <span className="h-10 w-10 rounded-xl bg-surface text-muted-foreground grid place-items-center shrink-0">
        <Icon className="h-5 w-5" />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-[14px] font-medium">{title}</div>
        {desc && <div className="text-[12.5px] text-muted-foreground mt-0.5">{desc}</div>}
      </div>
      {children}
    </div>
  );
}

export default function Settings() {
  const USAGE = useRealUsage();
  return (
    <div>
      <PageHeader title="Settings" subtitle="Manage your workspace, channels, and preferences." />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          <SectionCard title="Workspace" bodyClassName="divide-y divide-border">
            <Row icon={User} title="Business profile" desc="Name, logo, currency, and contact details.">
              <button className="h-8 px-3 rounded-lg border border-border text-[12.5px] font-medium hover:bg-surface">Edit</button>
            </Row>
            <Row icon={Palette} title="Appearance" desc="Theme and locale for your dashboard.">
              <Badge tone="muted">Light · English</Badge>
            </Row>
            <Row icon={Bell} title="Notifications" desc="What you get alerted about, and where.">
              <button className="h-8 px-3 rounded-lg border border-border text-[12.5px] font-medium hover:bg-surface">Manage</button>
            </Row>
            <Row icon={Shield} title="Team & roles" desc={`${USAGE.team.used} of ${USAGE.team.limit} seats in use.`}>
              <button className="h-8 px-3 rounded-lg border border-border text-[12.5px] font-medium hover:bg-surface">Invite</button>
            </Row>
          </SectionCard>

          <SectionCard title="Connected channels" bodyClassName="space-y-3">
            {CHANNELS.map((c) => (
              <div key={c.id} className="flex items-center gap-3 p-3 rounded-xl border border-border">
                <ChannelIcon channel={c.id} />
                <div className="flex-1">
                  <div className="text-[13.5px] font-medium">{c.label}</div>
                  <div className="text-[12px] text-muted-foreground">{c.connected ? "Connected" : "Not connected"}</div>
                </div>
                <Badge tone={c.connected ? "success" : "muted"}>
                  {c.connected ? "Active" : "Off"}
                </Badge>
                <button className="h-8 px-3 rounded-lg border border-border text-[12.5px] font-medium hover:bg-surface">
                  {c.connected ? "Manage" : "Connect"}
                </button>
              </div>
            ))}
          </SectionCard>
        </div>

        <div className="space-y-5">
          <SectionCard title="Plan & billing">
            <div className="rounded-xl bg-surface p-4">
              <div className="flex items-center justify-between">
                <span className="text-[12.5px] text-muted-foreground">Current plan</span>
                <Badge tone="primary">{USAGE.plan}</Badge>
              </div>
              <div className="mt-3 space-y-3">
                <div>
                  <div className="flex justify-between text-[12.5px] mb-1.5">
                    <span className="text-muted-foreground">AI credits</span>
                    <span className="tabular-nums">{USAGE.aiUsage.used.toLocaleString()}</span>
                  </div>
                  {USAGE.aiUsage.limit != null && <ProgressBar used={USAGE.aiUsage.used} limit={USAGE.aiUsage.limit} tone="accent" />}
                </div>
                <div>
                  <div className="flex justify-between text-[12.5px] mb-1.5">
                    <span className="text-muted-foreground">Conversations</span>
                    <span className="tabular-nums">{USAGE.conversations.used == null ? "—" : USAGE.conversations.used.toLocaleString()}</span>
                  </div>
                  <ProgressBar used={USAGE.conversations.used} limit={USAGE.conversations.limit} tone="primary" />
                </div>
                <div>
                  <div className="flex justify-between text-[12.5px] mb-1.5">
                    <span className="text-muted-foreground">Team seats</span>
                    <span className="tabular-nums">{USAGE.team.used == null ? "—" : USAGE.team.used}</span>
                  </div>
                  <ProgressBar used={USAGE.team.used} limit={USAGE.team.limit} tone="warning" />
                </div>
              </div>
            </div>
            <button className="mt-4 w-full h-9 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center justify-center gap-1.5">
              <CreditCard className="h-4 w-4" /> Manage billing
            </button>
          </SectionCard>

          <SectionCard title="Danger zone" bodyClassName="pt-1">
            <div className="py-3">
              <div className="text-[13px] font-medium">Archive workspace</div>
              <p className="text-[12px] text-muted-foreground mt-0.5">Pause all channels and AI agents.</p>
              <button className="mt-3 h-8 px-3 rounded-lg border border-destructive/30 text-destructive text-[12.5px] font-medium hover:bg-destructive/5">
                Archive
              </button>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
