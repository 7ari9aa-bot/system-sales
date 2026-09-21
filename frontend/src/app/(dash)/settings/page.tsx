"use client";

import * as React from "react";
import { Plug, UserPlus, Users, Copy, Check } from "lucide-react";
import {
  useCreateInvitation,
  useIntegrations,
  useInvitations,
  useRevokeInvitation,
  type Integration,
  type Invitation,
} from "@/lib/queries";
import { t } from "@/lib/t";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, PageHeader } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

export default function SettingsPage() {
  const [email, setEmail] = React.useState("");
  const [roleCode, setRoleCode] = React.useState("staff");
  const [created, setCreated] = React.useState<Invitation | null>(null);
  const [copied, setCopied] = React.useState(false);
  // §104 — الإلغاء إجراء خطر: يمر من نافذة تأكيد قبل أي DELETE
  const [revokeTarget, setRevokeTarget] = React.useState<Invitation | null>(null);

  function inviteLink(token: string) {
    return `${window.location.origin}/accept?token=${token}`;
  }

  function copyInviteLink() {
    if (!created?.token) return;
    navigator.clipboard
      .writeText(inviteLink(created.token))
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        /* الكليبورد مش متاح — المستخدم ينسخ الرابط يدويًا */
      });
  }

  const invitationsQuery = useInvitations();
  const integrationsQuery = useIntegrations();
  const invite = useCreateInvitation();

  const invitations = invitationsQuery.data ?? [];
  const integrations = integrationsQuery.data ?? [];
  const revoke = useRevokeInvitation();

  React.useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("new") === "1") {
      document.getElementById("inv-email")?.focus();
    }
  }, []);

  function submit() {
    if (!email.trim()) return;
    setCreated(null);
    invite.mutate(
      { email, role_code: roleCode },
      {
        onSuccess: (invitation) => {
          setCreated(invitation);
          setEmail("");
        },
      },
    );
  }

  return (
    <div>
      <PageHeader title={t.settings} description="الفريق والتكاملات" />

      {invitationsQuery.isError || integrationsQuery.isError ? (
        <EmptyState
          title={(invitationsQuery.error as Error | undefined ?? integrationsQuery.error as Error).message}
        />
      ) : invitationsQuery.isLoading || integrationsQuery.isLoading ? (
        <div className="space-y-4" aria-busy="true" aria-label={t.loading}>
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <Tabs defaultValue="team">
          <TabsList>
            <TabsTrigger value="team">{t.team}</TabsTrigger>
            <TabsTrigger value="integrations">{t.integrations}</TabsTrigger>
          </TabsList>

          {/* team + invitations */}
          <TabsContent value="team">
            <Card>
              <CardHeader>
                <CardTitle>{t.invite}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 sm:grid-cols-[1fr_180px_auto] sm:items-end">
                  <div>
                    <Label htmlFor="inv-email">{t.email}</Label>
                    <Input
                      id="inv-email"
                      type="email"
                      dir="ltr"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  <div>
                    <Label htmlFor="inv-role">{t.role}</Label>
                    <Select id="inv-role" value={roleCode} onChange={(e) => setRoleCode(e.target.value)}>
                      <option value="staff">{t.staff}</option>
                      <option value="manager">{t.manager}</option>
                      <option value="owner">{t.owner}</option>
                    </Select>
                  </div>
                  <Button
                    onClick={submit}
                    disabled={invite.isPending || !email.trim()}
                    data-testid="create-invitation"
                  >
                    <UserPlus aria-hidden="true" />
                    {t.invite}
                  </Button>
                </div>

                {created?.token && (
                  <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-muted px-3 py-2 text-[13px] text-muted-foreground">
                    <span>{t.acceptLink}:</span>
                    <a
                      href={inviteLink(created.token)}
                      dir="ltr"
                      className="min-w-0 truncate font-bold underline underline-offset-2"
                    >
                      /accept?token={created.token}
                    </a>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ms-auto h-7 gap-1.5 px-2 text-xs"
                      onClick={copyInviteLink}
                      data-testid="copy-invite-link"
                    >
                      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                      {copied ? "تم النسخ" : "نسخ"}
                    </Button>
                  </div>
                )}

                {invitations.length === 0 ? (
                  <EmptyState
                    icon={<Users aria-hidden="true" />}
                    title={t.noInvitations}
                    description={t.noInvitationsHint}
                    className="mt-2"
                  />
                ) : (
                  <div className="mt-4">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t.email}</TableHead>
                          <TableHead>{t.role}</TableHead>
                          <TableHead>{t.status}</TableHead>
                          <TableHead className="w-24 text-end"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {invitations.map((inv: Invitation) => (
                          <TableRow key={inv.id}>
                            <TableCell dir="ltr">{inv.email}</TableCell>
                            <TableCell>{inv.role_code ?? "—"}</TableCell>
                            <TableCell>
                              <Badge variant={inv.status === "pending" ? "warning" : "success"}>
                                {inv.status === "pending" ? t.pendingStatus : inv.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-end">
                              {inv.status === "pending" && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="text-xs text-danger hover:text-danger hover:bg-danger/10 h-7 px-2"
                                  disabled={revoke.isPending}
                                  onClick={() => setRevokeTarget(inv)}
                                  data-testid={`revoke-invitation-${inv.id}`}
                                >
                                  {t.revoke}
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* integrations */}
          <TabsContent value="integrations">
            <Card>
              <CardHeader>
                <CardTitle>{t.integrations}</CardTitle>
              </CardHeader>
              <CardContent className="p-0 pb-2">
                {integrations.length === 0 ? (
                  <EmptyState
                    icon={<Plug aria-hidden="true" />}
                    title={t.noIntegrations}
                    description={t.noIntegrationsHint}
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t.channelProvider}</TableHead>
                        <TableHead>{t.kind}</TableHead>
                        <TableHead>{t.status}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {integrations.map((i: Integration) => (
                        <TableRow key={i.id}>
                          <TableCell className="font-semibold">{i.provider}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{i.kind}</Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={i.status === "connected" ? "success" : "danger"}>
                              {i.status === "connected" ? t.connected : t.disconnected}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}

      {/* §104 — تأكيد قبل إلغاء الدعوة */}
      <ConfirmDialog
        open={Boolean(revokeTarget)}
        onOpenChange={(open) => {
          if (!open) setRevokeTarget(null);
        }}
        title={t.revokeConfirmTitle}
        description={t.revokeConfirmBody}
        confirmLabel={t.revokeConfirmAction}
        pending={revoke.isPending}
        onConfirm={() => {
          if (!revokeTarget) return;
          revoke.mutate(revokeTarget.id, { onSettled: () => setRevokeTarget(null) });
        }}
      />
    </div>
  );
}
